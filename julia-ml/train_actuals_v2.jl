#!/usr/bin/env julia
"""
Julia XGBoost Training - Actuals-Only (ACTUALS-FIRST methodology)

Trains forecast models on actual wait times with temporal features ONLY.
No posted_time — POSTED is used only for conversion (synthetic actuals);
forecasting deals in actuals.

Features: mins_since_6am, mins_since_open, date_group_id_encoded,
          season_encoded, season_year_encoded (5 features, no posted_time)
Model label: XGBOOST_ACTUALS_V1
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
const MODEL_LABEL = "XGBOOST_ACTUALS_V1"
const LITE_MODEL_LABEL = "XGBOOST_ACTUALS_LITE"

# 5 features — NO posted_time
const FEATURE_COLS_ACTUALS = [
    :mins_since_6am,
    :mins_since_open,
    :date_group_id_encoded,
    :season_encoded,
    :season_year_encoded,
]

# Lite: 2 features only (for entities with <500 obs)
const FEATURE_COLS_ACTUALS_LITE = [
    :mins_since_6am,
    :mins_since_open,
]

"""Train actuals-only XGBoost model for a single entity."""
function train_single_entity_actuals(entity_code::String, df::DataFrame, models_dir::String, min_samples::Int)
    entity_df = filter(row -> row.entity_code == entity_code, df)

    if nrow(entity_df) < min_samples
        return nothing, "Not enough samples ($(nrow(entity_df)))"
    end

    mins_since_open = coalesce.(entity_df.mins_since_open, 0.0)
    X = Matrix{Float32}(hcat(
        Float32.(entity_df.mins_since_6am),
        Float32.(mins_since_open),
        Float32.(entity_df.date_group_id_encoded),
        Float32.(entity_df.season_encoded),
        Float32.(entity_df.season_year_encoded),
    ))
    y = Float32.(entity_df.actual_time)

    # Geo decay + inverse frequency weighting for synthetic data
    # synth_weight = 1.0 / log2(n_real + 1) — less synthetic influence when more real data exists
    today_date = Dates.today()
    park_dates = Date.(string.(entity_df.park_date))
    days_old = Float32.(Dates.value.(today_date .- park_dates))
    geo_weights = Float32.(0.5 .^ (days_old ./ 730.0))

    if "is_synthetic" in names(entity_df)
        n_real = sum(.!entity_df.is_synthetic)
        synth_mult = n_real > 0 ? Float32(1.0 / log2(n_real + 1)) : 1.0f0
        weights = geo_weights .* ifelse.(entity_df.is_synthetic, synth_mult, 1.0f0)
    else
        weights = geo_weights
    end

    valid = .!isnan.(y) .& (y .> 0) .& .!isnan.(weights)
    X = X[valid, :]
    y = y[valid]
    weights = weights[valid]

    if length(y) < min_samples
        return nothing, "Not enough valid samples ($(length(y)))"
    end

    n = length(y)
    train_end = floor(Int, n * 0.85)
    X_train, y_train = X[1:train_end, :], y[1:train_end]
    X_val, y_val = X[train_end+1:end, :], y[train_end+1:end]
    weights_train = weights[1:train_end]

    dtrain = DMatrix(X_train, label=y_train)
    XGBoost.setinfo!(dtrain, "weight", weights_train)
    dval = DMatrix(X_val, label=y_val)
    watchlist = OrderedDict("train" => dtrain, "eval" => dval)

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

    y_pred = XGBoost.predict(bst, dval)
    mae = mean(abs.(y_val .- y_pred))

    model_dir = joinpath(models_dir, entity_code)
    mkpath(model_dir)
    model_path = joinpath(model_dir, "model_julia_actuals.json")
    XGBoost.save(bst, model_path)

    metadata = Dict(
        "model_label" => MODEL_LABEL,
        "entity_code" => entity_code,
        "trained_at" => Dates.format(now(Dates.UTC), "yyyy-mm-ddTHH:MM:SS"),
        "n_samples" => train_end,
        "n_val" => n - train_end,
        "mae" => mae,
        "features" => string.(FEATURE_COLS_ACTUALS),
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
        "version" => "actuals_v1",
    )
    metadata_path = joinpath(model_dir, "metadata_julia_actuals.json")
    open(metadata_path, "w") do f
        JSON3.write(f, metadata)
    end

    return train_end, mae
end

"""Train lite actuals model (2 features) for entities with 100-499 obs."""
function train_single_entity_actuals_lite(entity_code::String, df::DataFrame, models_dir::String, min_samples::Int)
    entity_df = filter(row -> row.entity_code == entity_code, df)

    if nrow(entity_df) < min_samples
        return nothing, "Not enough samples"
    end

    mins_since_open = coalesce.(entity_df.mins_since_open, 0.0)
    X = Matrix{Float32}(hcat(
        Float32.(entity_df.mins_since_6am),
        Float32.(mins_since_open),
    ))
    y = Float32.(entity_df.actual_time)

    valid = .!isnan.(y) .& (y .> 0)
    X = X[valid, :]
    y = y[valid]

    if length(y) < min_samples
        return nothing, "Not enough valid samples"
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
                  max_depth=6,
                  eta=0.1,
                  min_child_weight=3,
                  subsample=0.8,
                  colsample_bytree=0.8,
                  objective="reg:squarederror",
                  seed=42,
                  early_stopping_rounds=20,
                  verbosity=0)

    y_pred = XGBoost.predict(bst, dval)
    mae = mean(abs.(y_val .- y_pred))

    model_dir = joinpath(models_dir, entity_code)
    mkpath(model_dir)
    model_path = joinpath(model_dir, "model_julia_actuals.json")
    XGBoost.save(bst, model_path)

    metadata = Dict(
        "model_label" => LITE_MODEL_LABEL,
        "entity_code" => entity_code,
        "trained_at" => Dates.format(now(Dates.UTC), "yyyy-mm-ddTHH:MM:SS"),
        "n_samples" => train_end,
        "n_val" => n - train_end,
        "mae" => mae,
        "features" => string.(FEATURE_COLS_ACTUALS_LITE),
        "uses_geo_decay_weights" => false,
        "backend" => "Julia XGBoost.jl",
        "version" => "actuals_lite",
    )
    metadata_path = joinpath(model_dir, "metadata_julia_actuals.json")
    open(metadata_path, "w") do f
        JSON3.write(f, metadata)
    end

    return train_end, mae
end

function main()
    output_base = get(ENV, "OUTPUT_BASE", "/home/wilma/hazeydata/pipeline")
    actuals_dir = joinpath(output_base, "matched_pairs", "actuals_training_v2")
    actuals_single = joinpath(output_base, "matched_pairs", "actuals_training_v2.parquet")
    models_dir = joinpath(output_base, "models")
    entity_filter_path = joinpath(output_base, "state", "entities_to_train.txt")

    # Prefer per-park directory (OOM-safe); fallback to single file
    park_files = isdir(actuals_dir) ? sort([f for f in readdir(actuals_dir, join=true) if endswith(f, ".parquet")]) : String[]
    use_park_chunks = !isempty(park_files)

    if !use_park_chunks && !isfile(actuals_single)
        println("ERROR: Actuals training data not found: ", actuals_dir, " or ", actuals_single)
        println("Run: python scripts/build_actuals_training_data.py --output-base ", output_base)
        return 0
    end

    min_obs = DEFAULT_MIN_OBS

    println("=" ^ 60)
    println("JULIA XGBOOST TRAINING - ACTUALS-ONLY ($MODEL_LABEL)")
    println("=" ^ 60)
    println("Features: ", join(string.(FEATURE_COLS_ACTUALS), ", "), " (NO posted_time)")
    println("Weights: geo_decay + inverse_freq (real=1.0x, synthetic=1/log2(n_real+1))")
    println("OOM-safe: ", use_park_chunks ? "per-park chunks" : "single file")
    println("Threads: ", Threads.nthreads())

    # Build entity counts (from per-park files = small reads, or single file)
    println("\nScanning entity counts...")
    entity_counts = Dict{String, Int}()
    if use_park_chunks
        for f in park_files
            df = DataFrame(Parquet2.Dataset(f))
            for row in eachrow(combine(groupby(df, :entity_code), nrow => :count))
                entity_counts[row.entity_code] = get(entity_counts, row.entity_code, 0) + row.count
            end
        end
    else
        ds = Parquet2.Dataset(actuals_single)
        for row in eachrow(combine(groupby(DataFrame(entity_code = ds.entity_code), :entity_code), nrow => :count))
            entity_counts[row.entity_code] = row.count
        end
    end
    eligible_entities = [e for (e, c) in entity_counts if c >= min_obs]

    if isfile(entity_filter_path)
        dirty_entities = Set(strip.(readlines(entity_filter_path)))
        entities_to_train = filter(e -> e in dirty_entities, eligible_entities)
        println("Eligible: ", length(eligible_entities), " | Dirty: ", length(dirty_entities), " | To train: ", length(entities_to_train))
    else
        entities_to_train = eligible_entities
        println("No entity filter — training all eligible: ", length(entities_to_train))
    end

    # Map entity -> park for chunked loading
    entity_to_park(e) = startswith(e, "USH") ? "UH" : startswith(e, "TDL") ? "TDL" : startswith(e, "TDS") ? "TDS" : e[1:min(2, end)]
    park_to_entities = Dict{String, Vector{String}}()
    for e in entities_to_train
        push!(get!(park_to_entities, entity_to_park(e), String[]), e)
    end

    println("\n" * "=" ^ 60)
    println("TRAINING ", length(entities_to_train), " ACTUALS MODELS")
    println("=" ^ 60)

    train_start = time()
    successful = 0
    failed = 0
    total_mae = 0.0

    for (park_code, park_entities) in sort(collect(park_to_entities))
        # Load only this park's parquet (OOM-safe: one park at a time)
        park_path = use_park_chunks ? joinpath(actuals_dir, park_code * ".parquet") : actuals_single
        if use_park_chunks && !isfile(park_path)
            continue
        end
        park_df = DataFrame(Parquet2.Dataset(park_path))
        if use_park_chunks
            park_df = filter(row -> row.entity_code in park_entities, park_df)
        end
        if nrow(park_df) == 0
            continue
        end

        for entity in park_entities
            result, msg = train_single_entity_actuals(entity, park_df, models_dir, 100)
            if result !== nothing
                successful += 1
                total_mae += msg
            else
                failed += 1
            end
            if (successful + failed) % 20 == 0
                println("  Park ", park_code, ": ", successful + failed, " done (", round(time() - train_start, digits=1), "s)")
            end
        end
    end

    elapsed = time() - train_start

    println("\n" * "=" ^ 60)
    println("ACTUALS TRAINING COMPLETE")
    println("=" ^ 60)
    println("Model: ", MODEL_LABEL)
    println("Successful: ", successful)
    println("Failed: ", failed)
    if successful > 0
        println("Avg MAE: ", round(total_mae / successful, digits=2), " minutes")
    end
    println("Time: ", round(elapsed, digits=1), "s")
    println("Models: ", models_dir, " (model_julia_actuals.json)")

    # Lite models (100-499 obs)
    lite_eligible = [e for (e, c) in entity_counts if LITE_MIN_OBS <= c < min_obs]
    trained = Set(entities_to_train)
    if isfile(entity_filter_path)
        dirty_set = Set(strip.(readlines(entity_filter_path)))
        lite_to_train = filter(e -> (e in dirty_set) && !(e in trained), lite_eligible)
    else
        lite_to_train = filter(e -> !(e in trained), lite_eligible)
    end
    lite_to_train = filter(e -> !isfile(joinpath(models_dir, e, "model_julia_actuals.json")), lite_to_train)

    if !isempty(lite_to_train)
        println("\n" * "=" ^ 60)
        println("TRAINING ", length(lite_to_train), " ACTUALS LITE MODELS")
        println("=" ^ 60)
        lite_successful = 0
        for entity in lite_to_train
            park = entity_to_park(entity)
            park_path = use_park_chunks ? joinpath(actuals_dir, park * ".parquet") : actuals_single
            isfile(park_path) || continue
            park_df = filter(row -> row.entity_code == entity, DataFrame(Parquet2.Dataset(park_path)))
            result, _ = train_single_entity_actuals_lite(entity, park_df, models_dir, 50)
            if result !== nothing
                lite_successful += 1
            end
        end
        successful += lite_successful
        println("Lite: ", lite_successful, " trained")
    end

    return successful
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
