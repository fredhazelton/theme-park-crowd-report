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
const MODEL_LABEL = "XGBOOST_BASE_MODEL"

# Feature columns in order - must match Python
const FEATURE_COLS_V2 = [
    :posted_time,
    :mins_since_6am,
    :hour_of_day,
    :date_group_id_encoded,
    :season_encoded,
    :season_year_encoded,
]

"""Train XGBoost model for a single entity with geo decay weights."""
function train_single_entity_v2(entity_code::String, matched_df::DataFrame, models_dir::String, min_samples::Int)
    # Filter for this entity
    entity_df = filter(row -> row.entity_code == entity_code, matched_df)
    
    if nrow(entity_df) < min_samples
        return nothing, "Not enough samples ($(nrow(entity_df)))"
    end
    
    # Build feature matrix
    X = Matrix{Float32}(hcat(
        Float32.(entity_df.posted_time),
        Float32.(entity_df.mins_since_6am),
        Float32.(entity_df.hour_of_day),
        Float32.(entity_df.date_group_id_encoded),
        Float32.(entity_df.season_encoded),
        Float32.(entity_df.season_year_encoded),
    ))
    y = Float32.(entity_df.actual_time)
    weights = Float32.(entity_df.geo_decay_weight)
    
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
                  num_round=500,
                  watchlist=watchlist,
                  max_depth=6,
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
            "num_round" => 500,
            "max_depth" => 6,
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

function main()
    # Try V2 pairs first, fallback to V1
    matched_pairs_v2 = "/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs_v2.parquet"
    matched_pairs_v1 = "/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs.parquet"
    
    if isfile(matched_pairs_v2)
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
    
    # Check for required columns
    required_cols = [:posted_time, :mins_since_6am, :hour_of_day, 
                     :date_group_id_encoded, :season_encoded, :season_year_encoded,
                     :geo_decay_weight, :actual_time, :entity_code]
    
    missing_cols = [c for c in required_cols if !(String(c) in names(matched_df))]
    if !isempty(missing_cols)
        println("ERROR: Missing columns: $missing_cols")
        println("Available columns: $(names(matched_df))")
        return 0, 0.0
    end
    
    # Get entities with enough data
    entity_counts = combine(groupby(matched_df, :entity_code), nrow => :count)
    entities_to_train = filter(row -> row.count >= min_obs, entity_counts).entity_code
    
    println("\nEntities to train: $(length(entities_to_train))")
    
    # Train models
    println("\n" * "=" ^ 60)
    println("TRAINING $(length(entities_to_train)) ENTITY MODELS")
    println("=" ^ 60)
    
    train_start = time()
    successful = 0
    failed = 0
    total_mae = 0.0
    
    for (i, entity) in enumerate(entities_to_train)
        result, msg = train_single_entity_v2(entity, matched_df, models_dir, 100)
        
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
    println("Successful: $successful")
    println("Failed: $failed")
    if successful > 0
        println("Avg MAE: $(round(total_mae / successful, digits=2)) minutes")
    end
    println("Training time: $(round(elapsed, digits=1))s")
    println("Per entity: $(round(elapsed / max(1, length(entities_to_train)), digits=2))s")
    println("Models saved to: $models_dir")
    
    return successful, elapsed
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
