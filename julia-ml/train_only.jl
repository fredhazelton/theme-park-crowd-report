#!/usr/bin/env julia
"""
Julia XGBoost Training Benchmark

Uses Python-generated matched pairs (DuckDB is faster for that).
Only benchmarks the XGBoost training step.
"""

using Dates
using DataFrames
using Parquet2
using JSON3
using XGBoost
using Statistics
using OrderedCollections

const DEFAULT_MIN_OBS = 500

"""Train XGBoost model for a single entity."""
function train_single_entity(entity_code::String, matched_df::DataFrame, models_dir::String, min_samples::Int)
    # Filter for this entity
    entity_df = filter(row -> row.entity_code == entity_code, matched_df)
    
    if nrow(entity_df) < min_samples
        return nothing, "Not enough samples ($(nrow(entity_df)))"
    end
    
    # Prepare features - must match Python feature order
    feature_cols = [:posted_time, :mins_since_6am, :hour_of_day, :day_of_week, :month, :is_weekend]
    
    # Build feature matrix
    X = Matrix{Float32}(hcat(
        Float32.(entity_df.posted_time),
        Float32.(entity_df.mins_since_6am),
        Float32.(entity_df.hour_of_day),
        Float32.(entity_df.day_of_week),
        Float32.(entity_df.month),
        Float32.(entity_df.is_weekend)
    ))
    y = Float32.(entity_df.actual_time)
    
    # Remove invalid
    valid = .!isnan.(y) .& (y .> 0)
    X = X[valid, :]
    y = y[valid]
    
    if length(y) < min_samples
        return nothing, "Not enough valid samples ($(length(y)))"
    end
    
    # Train/val split (chronological - 85/15)
    n = length(y)
    train_end = floor(Int, n * 0.85)
    
    X_train, y_train = X[1:train_end, :], y[1:train_end]
    X_val, y_val = X[train_end+1:end, :], y[train_end+1:end]
    
    # Train XGBoost
    dtrain = DMatrix(X_train, label=y_train)
    dval = DMatrix(X_val, label=y_val)
    
    watchlist = OrderedDict("train" => dtrain, "eval" => dval)
    
    bst = xgboost(dtrain;
                  num_round=500,
                  watchlist=watchlist,
                  max_depth=6,
                  eta=0.1,
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
    XGBoost.save(bst, joinpath(model_dir, "model_julia.json"))
    
    # Save metadata
    metadata = Dict(
        "entity_code" => entity_code,
        "trained_at" => Dates.format(now(Dates.UTC), "yyyy-mm-ddTHH:MM:SS"),
        "n_samples" => train_end,
        "mae" => mae,
        "features" => string.(feature_cols),
        "backend" => "Julia XGBoost.jl",
    )
    open(joinpath(model_dir, "metadata_julia.json"), "w") do f
        JSON3.write(f, metadata)
    end
    
    return train_end, mae
end

function main()
    matched_pairs_path = "/home/wilma/hazeydata/pipeline/matched_pairs/all_pairs.parquet"
    models_dir = "/home/wilma/hazeydata/pipeline/models"
    min_obs = DEFAULT_MIN_OBS
    
    println("=" ^ 60)
    println("JULIA XGBOOST TRAINING BENCHMARK")
    println("=" ^ 60)
    println("Using Python-generated matched pairs (DuckDB is faster)")
    println("Threads: $(Threads.nthreads())")
    
    # Load matched pairs
    println("\nLoading matched pairs...")
    load_start = time()
    matched_df = DataFrame(Parquet2.Dataset(matched_pairs_path))
    println("  Loaded $(nrow(matched_df)) pairs in $(round(time() - load_start, digits=1))s")
    
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
        result, msg = train_single_entity(entity, matched_df, models_dir, 100)
        
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
    println("TRAINING COMPLETE")
    println("=" ^ 60)
    println("Successful: $successful")
    println("Failed: $failed")
    println("Avg MAE: $(round(total_mae / successful, digits=2)) minutes")
    println("Training time: $(round(elapsed, digits=1))s")
    println("Per entity: $(round(elapsed / length(entities_to_train), digits=2))s")
    println("Models saved to: $models_dir")
    
    return successful, elapsed
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
