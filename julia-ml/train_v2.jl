#!/usr/bin/env julia
"""
Julia XGBoost Training V2 - With Geo Decay Weights

Changes from V1:
- Uses geo_decay_weight as sample weights (recent data weighs more)
- New features: date_group_id, season, season_year (encoded)
- Removed: day_of_week, month, is_weekend
- Model labeled as XGBOOST_BASE_MODEL
"""

using Dates
using DataFrames
using Parquet2
using JSON3
using XGBoost
using Statistics
using OrderedCollections

const DEFAULT_MIN_OBS = 500
const LITE_MIN_OBS = 100
const MODEL_LABEL = "XGBOOST_BASE_MODEL"
const LITE_MODEL_LABEL = "XGBOOST_LITE_MODEL"

# Feature columns in order - must match Python
const FEATURE_COLS_V2 = [
    :posted_time,
    :mins_since_6am,
    :mins_since_open,
    :hour_of_day,
    :date_group_id_encoded,
    :season_encoded,
    :season_year_encoded,
]

# Lite features: no calendar features, works for new entities with <1 year of data
const FEATURE_COLS_LITE = [
    :posted_time,
    :mins_since_6am,
    :mins_since_open,
    :hour_of_day,
]

"""Train XGBoost model for a single entity with geo decay weights and optional synthetic balance."""
function train_single_entity_v2(entity_code::String, matched_df::DataFrame, models_dir::String, min_samples::Int, use_synthetic::Bool=false)
    # Filter for this entity
    entity_df = filter(row -> row.entity_code == entity_code, matched_df)
    
    if nrow(entity_df) < min_samples
        return nothing, "Not enough samples ($(nrow(entity_df)))"
    end
    
    # Build feature matrix (handle NULL mins_since_open with 0)
    mins_since_open = coalesce.(entity_df.mins_since_open, 0.0)
    X = Matrix{Float32}(hcat(
        Float32.(entity_df.posted_time),
        Float32.(entity_df.mins_since_6am),
        Float32.(mins_since_open),
        Float32.(entity_df.hour_of_day),
        Float32.(entity_df.date_group_id_encoded),
        Float32.(entity_df.season_encoded),
        Float32.(entity_df.season_year_encoded),
    ))
    y = Float32.(entity_df.actual_time)
    
    # Compute geo decay weights at training time: 0.5^(days_old / 730)
    today_date = Dates.today()
    park_dates = Date.(string.(entity_df.park_date))
    days_old = Float32.(Dates.value.(today_date .- park_dates))
    geo_weights = Float32.(0.5 .^ (days_old ./ 730.0))
    
    # Apply uniform weighting if using synthetic data
    if use_synthetic && "is_synthetic" in names(entity_df)
        is_synthetic = entity_df.is_synthetic
        n_real = sum(.!is_synthetic)
        n_synthetic = sum(is_synthetic)
        
        # Inverse frequency weighting: synthetic weight decreases as real data increases
        # synth_weight = 1.0 / log2(n_real + 1) — entities with more real data rely less on synthetic
        # Real observations always get weight 1.0 × geo_decay
        # Tested 7 schemes on 15 entities (Mar 6 2026): inverse_freq won (MAE 6.96 vs 7.04 uniform_3.5)
        synth_mult = n_real > 0 ? Float32(1.0 / log2(n_real + 1)) : 1.0f0
        weights = geo_weights .* ifelse.(is_synthetic, synth_mult, 1.0f0)
        
        if n_real > 0 && n_synthetic > 0
            println("  Entity $entity_code: $n_real real (1.0x weight), $n_synthetic synthetic ($(round(synth_mult, digits=4))x weight)")
        end
    else
        weights = geo_weights
    end
    
    # Remove invalid rows
    valid = .!isnan.(y) .& (y .> 0) .& .!isnan.(weights)
    X = X[valid, :]
    y = y[valid]
    weights = weights[valid]
    
    if length(y) < min_samples
        return nothing, "Not enough valid samples ($(length(y)))"
    end
    
    # Chronological train/val split (85/15)
    n = length(y)
    train_end = floor(Int, n * 0.85)
    
    X_train, y_train = X[1:train_end, :], y[1:train_end]
    X_val, y_val = X[train_end+1:end, :], y[train_end+1:end]
    weights_train = weights[1:train_end]
    
    # Create DMatrix with weights
    dtrain = DMatrix(X_train, label=y_train)
    XGBoost.setinfo!(dtrain, "weight", weights_train)
    
    dval = DMatrix(X_val, label=y_val)
    
    watchlist = OrderedDict("train" => dtrain, "eval" => dval)
    
    # Train XGBoost with specified hyperparameters
    bst = xgboost(dtrain;
                  num_round=2000,
                  watchlist=watchlist,
                  max_depth=10,
                  eta=0.1,
                  min_child_weight=1,
                  subsample=0.8,
                  colsample_bytree=0.8,
                  objective="reg:squarederror",
                  seed=42,
                  early_stopping_rounds=20,
                  verbosity=0)
    
    # Evaluate
    y_pred = XGBoost.predict(bst, dval)
    mae = mean(abs.(y_val .- y_pred))
    
    # Save model
    model_dir = joinpath(models_dir, entity_code)
    mkpath(model_dir)
    model_path = joinpath(model_dir, "model_julia_v2.json")
    XGBoost.save(bst, model_path)
    
    # Save metadata with full hyperparameters
    metadata = Dict(
        "model_label" => MODEL_LABEL,
        "entity_code" => entity_code,
        "trained_at" => Dates.format(now(Dates.UTC), "yyyy-mm-ddTHH:MM:SS"),
        "n_samples" => train_end,
        "n_val" => n - train_end,
        "mae" => mae,
        "features" => string.(FEATURE_COLS_V2),
        "uses_geo_decay_weights" => true,
        "geo_decay_halflife_days" => 730,
        "hyperparameters" => Dict(
            "num_round" => 2000,
            "max_depth" => 10,
            "eta" => 0.1,
            "min_child_weight" => 1,
            "subsample" => 0.8,
            "colsample_bytree" => 0.8,
            "objective" => "reg:squarederror",
            "early_stopping_rounds" => 20,
        ),
        "backend" => "Julia XGBoost.jl",
        "version" => "v2",
    )
    open(joinpath(model_dir, "metadata_julia_v2.json"), "w") do f
        JSON3.write(f, metadata)
    end
    
    return train_end, mae
end

"""Train lite XGBoost model for new entities — no calendar features, no geo decay."""
function train_single_entity_lite(entity_code::String, matched_df::DataFrame, models_dir::String, min_samples::Int)
    entity_df = filter(row -> row.entity_code == entity_code, matched_df)
    
    if nrow(entity_df) < min_samples
        return nothing, "Not enough samples ($(nrow(entity_df)))"
    end
    
    # Lite features only: posted_time, mins_since_6am, mins_since_open, hour_of_day
    mins_since_open = coalesce.(entity_df.mins_since_open, 0.0)
    X = Matrix{Float32}(hcat(
        Float32.(entity_df.posted_time),
        Float32.(entity_df.mins_since_6am),
        Float32.(mins_since_open),
        Float32.(entity_df.hour_of_day),
    ))
    y = Float32.(entity_df.actual_time)
    
    # No geo decay — all data is fresh for new entities
    # Equal weights
    valid = .!isnan.(y) .& (y .> 0)
    X = X[valid, :]
    y = y[valid]
    
    if length(y) < min_samples
        return nothing, "Not enough valid samples ($(length(y)))"
    end
    
    n = length(y)
    train_end = floor(Int, n * 0.85)
    
    X_train, y_train = X[1:train_end, :], y[1:train_end]
    X_val, y_val = X[train_end+1:end, :], y[train_end+1:end]
    
    dtrain = DMatrix(X_train, label=y_train)
    dval = DMatrix(X_val, label=y_val)
    watchlist = OrderedDict("train" => dtrain, "eval" => dval)
    
    bst = xgboost(dtrain;
                  num_round=2000,
                  watchlist=watchlist,
                  max_depth=6,      # Shallower — less data to learn from
                  eta=0.1,
                  min_child_weight=3,  # More conservative with less data
                  subsample=0.8,
                  colsample_bytree=0.8,
                  objective="reg:squarederror",
                  seed=42,
                  early_stopping_rounds=20,
                  verbosity=0)
    
    y_pred = XGBoost.predict(bst, dval)
    mae = mean(abs.(y_val .- y_pred))
    
    # Save as the same model file — forecast code picks it up automatically
    model_dir = joinpath(models_dir, entity_code)
    mkpath(model_dir)
    model_path = joinpath(model_dir, "model_julia_v2.json")
    XGBoost.save(bst, model_path)
    
    metadata = Dict(
        "model_label" => LITE_MODEL_LABEL,
        "entity_code" => entity_code,
        "trained_at" => Dates.format(now(Dates.UTC), "yyyy-mm-ddTHH:MM:SS"),
        "n_samples" => train_end,
        "n_val" => n - train_end,
        "mae" => mae,
        "features" => string.(FEATURE_COLS_LITE),
        "uses_geo_decay_weights" => false,
        "hyperparameters" => Dict(
            "num_round" => 2000,
            "max_depth" => 6,
            "eta" => 0.1,
            "min_child_weight" => 3,
            "subsample" => 0.8,
            "colsample_bytree" => 0.8,
            "objective" => "reg:squarederror",
            "early_stopping_rounds" => 20,
        ),
        "backend" => "Julia XGBoost.jl",
        "version" => "lite",
    )
    open(joinpath(model_dir, "metadata_julia_v2.json"), "w") do f
        JSON3.write(f, metadata)
    end
    
    return train_end, mae
end

function main()
    # Parse --data-path argument if provided (for per-park chunked training)
    explicit_data_path = nothing
    args = ARGS
    for i in eachindex(args)
        if args[i] == "--data-path" && i < length(args)
            explicit_data_path = args[i+1]
            break
        end
    end
    
    # Try combined pairs first (real + synthetic), then V2, then V1
    combined_pairs = "/home/wilma/hazeydata/pipeline/matched_pairs/combined_pairs_v2.parquet"
    matched_pairs_v2 = "/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs_v2.parquet"
    matched_pairs_v1 = "/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs.parquet"
    
    use_synthetic = false
    if explicit_data_path !== nothing
        # Explicit path provided (per-park chunk from Python wrapper)
        matched_pairs_path = explicit_data_path
        # Detect if this is a combined (real+synthetic) chunk by checking for is_synthetic column
        use_synthetic = true  # chunks are always from combined data
        println("Using explicit data path: $matched_pairs_path (per-park chunk)")
    elseif isfile(combined_pairs)
        matched_pairs_path = combined_pairs
        use_synthetic = true
        println("Using combined pairs (real + synthetic) with balanced weighting")
    elseif isfile(matched_pairs_v2)
        matched_pairs_path = matched_pairs_v2
        println("Using V2 matched pairs with geo_decay weights")
    elseif isfile(matched_pairs_v1)
        matched_pairs_path = matched_pairs_v1
        println("WARNING: V2 pairs not found, using V1 (no geo_decay)")
    else
        println("ERROR: No matched pairs file found")
        return 0, 0.0
    end
    
    models_dir = "/home/wilma/hazeydata/pipeline/models"
    min_obs = DEFAULT_MIN_OBS
    
    println("=" ^ 60)
    println("JULIA XGBOOST TRAINING V2 ($MODEL_LABEL)")
    println("=" ^ 60)
    println("Features: $(join(string.(FEATURE_COLS_V2), ", "))")
    println("Weights: geo_decay (half-life=730 days)")
    println("Threads: $(Threads.nthreads())")
    
    # Load matched pairs
    println("\nLoading matched pairs...")
    load_start = time()
    matched_df = DataFrame(Parquet2.Dataset(matched_pairs_path))
    println("  Loaded $(nrow(matched_df)) pairs in $(round(time() - load_start, digits=1))s")
    
    # Check for required columns (geo_decay_weight computed at training time from park_date)
    required_cols = [:posted_time, :mins_since_6am, :mins_since_open, :hour_of_day, 
                     :date_group_id_encoded, :season_encoded, :season_year_encoded,
                     :park_date, :actual_time, :entity_code]
    
    if use_synthetic
        push!(required_cols, :is_synthetic)
    end
    
    missing_cols = [c for c in required_cols if !(String(c) in names(matched_df))]
    if !isempty(missing_cols)
        println("ERROR: Missing columns: $missing_cols")
        println("Available columns: $(names(matched_df))")
        return 0, 0.0
    end
    
    # Check for entity filter file (dirty entities from Python/entity_index)
    entity_filter_path = "/home/wilma/hazeydata/pipeline/state/entities_to_train.txt"
    
    # Get entities with enough data
    entity_counts = combine(groupby(matched_df, :entity_code), nrow => :count)
    eligible_entities = filter(row -> row.count >= min_obs, entity_counts).entity_code
    
    if isfile(entity_filter_path)
        # Only train entities that are both eligible (≥500 pairs) AND dirty (new data)
        dirty_entities = Set(strip.(readlines(entity_filter_path)))
        entities_to_train = filter(e -> e in dirty_entities, eligible_entities)
        println("\nEligible entities (≥$(min_obs) pairs): $(length(eligible_entities))")
        println("Dirty entities (new data): $(length(dirty_entities))")
        println("Entities to train (eligible ∩ dirty): $(length(entities_to_train))")
    else
        # No filter file = train all eligible (backward compat / full retrain)
        entities_to_train = eligible_entities
        println("\nNo entity filter file — training all eligible entities")
        println("Entities to train: $(length(entities_to_train))")
    end
    
    # Train models
    println("\n" * "=" ^ 60)
    println("TRAINING $(length(entities_to_train)) ENTITY MODELS")
    println("=" ^ 60)
    
    train_start = time()
    successful = 0
    failed = 0
    total_mae = 0.0
    
    for (i, entity) in enumerate(entities_to_train)
        result, msg = train_single_entity_v2(entity, matched_df, models_dir, 100, use_synthetic)
        
        if result !== nothing
            successful += 1
            total_mae += msg  # msg is MAE when successful
        else
            failed += 1
        end
        
        if i % 20 == 0
            elapsed = time() - train_start
            rate = i / elapsed
            eta = (length(entities_to_train) - i) / rate
            println("  Trained $i/$(length(entities_to_train)) models... ($(round(rate, digits=1))/s, ETA $(round(eta, digits=0))s)")
        end
    end
    
    elapsed = time() - train_start
    
    println("\n" * "=" ^ 60)
    println("TRAINING V2 COMPLETE")
    println("=" ^ 60)
    println("Model: $MODEL_LABEL")
    if use_synthetic
        real_count = sum(.!matched_df.is_synthetic)
        synthetic_count = sum(matched_df.is_synthetic)
        println("Training data: $(size(matched_df, 1)) total ($real_count real + $synthetic_count synthetic)")
        println("Synthetic weighting: Applied to balance real vs synthetic observations")
    else
        println("Training data: $(size(matched_df, 1)) real observations only")
    end
    println("Successful: $successful")
    println("Failed: $failed")
    if successful > 0
        println("Avg MAE: $(round(total_mae / successful, digits=2)) minutes")
    end
    println("Training time: $(round(elapsed, digits=1))s")
    println("Per entity: $(round(elapsed / max(1, length(entities_to_train)), digits=2))s")
    println("Models saved to: $models_dir")
    
    # ================================================================
    # LITE MODELS: entities with 100-499 pairs (no calendar features, no geo decay)
    # For new parks/entities without a full year of seasonal data
    # ================================================================
    trained_v2 = Set(entities_to_train)  # Already have full models
    lite_eligible = filter(row -> row.count >= LITE_MIN_OBS && row.count < min_obs, entity_counts).entity_code
    # Also include entities with 500+ pairs that DON'T already have a V2 model on disk
    # (they might not be dirty but could benefit from a lite model if they've never been trained)
    
    if isfile(entity_filter_path)
        dirty_entities_set = Set(strip.(readlines(entity_filter_path)))
        lite_to_train = filter(e -> (e in dirty_entities_set) && !(e in trained_v2), lite_eligible)
    else
        lite_to_train = filter(e -> !(e in trained_v2), lite_eligible)
    end
    
    # Don't overwrite existing V2 models with lite models
    lite_to_train = filter(e -> !isfile(joinpath(models_dir, e, "model_julia_v2.json")) || 
                                 (e in (isfile(entity_filter_path) ? dirty_entities_set : Set())), lite_to_train)
    
    if !isempty(lite_to_train)
        println("\n" * "=" ^ 60)
        println("TRAINING $(length(lite_to_train)) LITE MODELS ($(LITE_MIN_OBS)-$(min_obs-1) pairs)")
        println("=" ^ 60)
        println("Features: $(join(string.(FEATURE_COLS_LITE), ", "))")
        println("No geo decay, no calendar features")
        
        lite_start = time()
        lite_successful = 0
        lite_failed = 0
        lite_total_mae = 0.0
        
        for (i, entity) in enumerate(lite_to_train)
            result, msg = train_single_entity_lite(entity, matched_df, models_dir, 50)
            
            if result !== nothing
                lite_successful += 1
                lite_total_mae += msg
            else
                lite_failed += 1
            end
        end
        
        lite_elapsed = time() - lite_start
        
        println("\n" * "=" ^ 60)
        println("LITE TRAINING COMPLETE")
        println("=" ^ 60)
        println("Model: $LITE_MODEL_LABEL")
        println("Successful: $lite_successful")
        println("Failed: $lite_failed")
        if lite_successful > 0
            println("Avg MAE: $(round(lite_total_mae / lite_successful, digits=2)) minutes")
        end
        println("Lite training time: $(round(lite_elapsed, digits=1))s")
        
        successful += lite_successful
    end
    
    return successful, elapsed
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
