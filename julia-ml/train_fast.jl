#!/usr/bin/env julia
"""
FAST Training Pipeline - Julia Version

Benchmarking Julia vs Python for XGBoost training.
Uses Parquet files, native threading, and XGBoost.jl.
"""

using Dates
using DataFrames
using Parquet2
using JSON3
using XGBoost
using Statistics

# Constants
const MATCH_WINDOW_MINUTES = 15
const DEFAULT_MIN_OBS = 500
const DEFAULT_FALLBACK_RATIO = 0.82

const PREDICTOR_COLUMNS = [
    :mins_since_6am,
    :hour_of_day,
    :day_of_week,
    :month,
    :is_weekend,
]

"""Load all parquet files from directory into a single DataFrame."""
function load_parquet_dir(dir::String)
    files = filter(f -> endswith(f, ".parquet"), readdir(dir, join=true))
    println("  Loading $(length(files)) parquet files...")
    
    dfs = DataFrame[]
    for f in files
        push!(dfs, DataFrame(Parquet2.Dataset(f)))
    end
    
    return vcat(dfs...)
end

"""Count ACTUAL observations per entity."""
function get_entity_counts(df::DataFrame)
    println("Counting ACTUAL observations...")
    
    actual_df = filter(row -> row.wait_time_type == "ACTUAL", df)
    counts = combine(groupby(actual_df, :entity_code), nrow => :actual_count)
    
    println("  Found $(nrow(counts)) entities with ACTUAL data")
    return Dict(row.entity_code => row.actual_count for row in eachrow(counts))
end

"""Create matched pairs (ACTUAL with closest POSTED within window)."""
function create_matched_pairs(df::DataFrame, output_path::String)
    println("Creating matched pairs...")
    
    # Split by type
    actual = filter(row -> row.wait_time_type == "ACTUAL" && 
                          !ismissing(row.wait_time_minutes) && 
                          row.wait_time_minutes > 0, df)
    posted = filter(row -> row.wait_time_type == "POSTED" && 
                          !ismissing(row.wait_time_minutes) && 
                          row.wait_time_minutes > 0, df)
    
    println("  ACTUAL rows: $(nrow(actual))")
    println("  POSTED rows: $(nrow(posted))")
    
    # Create lookup by (entity, park_date)
    posted_lookup = Dict{Tuple{String, Any}, Vector{NamedTuple}}()
    for row in eachrow(posted)
        key = (row.entity_code, row.park_date)
        if !haskey(posted_lookup, key)
            posted_lookup[key] = []
        end
        push!(posted_lookup[key], (ts=row.observed_at_ts, posted=row.wait_time_minutes))
    end
    
    # Match each ACTUAL with closest POSTED
    matched = NamedTuple[]
    window_sec = MATCH_WINDOW_MINUTES * 60
    
    for (i, row) in enumerate(eachrow(actual))
        if i % 100000 == 0
            println("  Processed $i / $(nrow(actual)) ACTUAL rows...")
        end
        
        key = (row.entity_code, row.park_date)
        candidates = get(posted_lookup, key, [])
        
        best_posted = nothing
        best_diff = Inf
        
        actual_ts = row.observed_at_ts
        
        for c in candidates
            diff = abs(Dates.value(actual_ts - c.ts) / 1000)  # milliseconds to seconds
            if diff <= window_sec && diff < best_diff
                best_diff = diff
                best_posted = c.posted
            end
        end
        
        if best_posted !== nothing
            push!(matched, (
                entity_code = row.entity_code,
                observed_at = row.observed_at,
                observed_at_ts = actual_ts,
                park_date = row.park_date,
                actual_time = row.wait_time_minutes,
                posted_time = best_posted,
            ))
        end
    end
    
    println("  Created $(length(matched)) matched pairs")
    
    # Convert to DataFrame and add features
    result = DataFrame(matched)
    
    result.hour_of_day = hour.(result.observed_at_ts)
    result.mins_since_6am = (hour.(result.observed_at_ts) .- 6) .* 60 .+ minute.(result.observed_at_ts)
    result.day_of_week = dayofweek.(result.observed_at_ts)
    result.month = month.(result.observed_at_ts)
    result.is_weekend = Int.(dayofweek.(result.observed_at_ts) .>= 6)
    
    # Save to parquet
    mkpath(dirname(output_path))
    Parquet2.writefile(output_path, result)
    println("  Saved to: $output_path")
    
    return result
end

"""Train XGBoost model for a single entity."""
function train_single_entity(entity_code::String, matched_df::DataFrame, models_dir::String, min_samples::Int)
    # Filter for this entity
    entity_df = filter(row -> row.entity_code == entity_code, matched_df)
    
    if nrow(entity_df) < min_samples
        return nothing, "Not enough samples ($(nrow(entity_df)))"
    end
    
    # Prepare features
    feature_cols = [:posted_time, :mins_since_6am, :hour_of_day, :day_of_week, :month, :is_weekend]
    X = Matrix{Float32}(entity_df[:, feature_cols])
    y = Float32.(entity_df.actual_time)
    
    # Remove invalid
    valid = .!isnan.(y) .& (y .> 0)
    X = X[valid, :]
    y = y[valid]
    
    if length(y) < min_samples
        return nothing, "Not enough valid samples ($(length(y)))"
    end
    
    # Train/val split (chronological)
    n = length(y)
    train_end = floor(Int, n * 0.85)
    
    X_train, y_train = X[1:train_end, :], y[1:train_end]
    X_val, y_val = X[train_end+1:end, :], y[train_end+1:end]
    
    # Train XGBoost
    dtrain = DMatrix(X_train, label=y_train)
    dval = DMatrix(X_val, label=y_val)
    
    params = Dict(
        "max_depth" => 6,
        "eta" => 0.1,
        "objective" => "reg:squarederror",
        "seed" => 42,
    )
    
    watchlist = [(dtrain, "train"), (dval, "eval")]
    
    bst = xgboost(dtrain, 500;
                  watchlist=watchlist,
                  params...,
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

"""Main training pipeline."""
function main(; parquet_dir::String="/home/wilma/hazeydata/pipeline/fact_tables/parquet",
               output_base::String="/home/wilma/hazeydata/pipeline",
               min_obs::Int=DEFAULT_MIN_OBS,
               skip_matching::Bool=false)
    
    models_dir = joinpath(output_base, "models")
    matched_pairs_path = joinpath(output_base, "matched_pairs", "all_pairs_julia.parquet")
    
    println("=" ^ 60)
    println("FAST TRAINING PIPELINE (Julia)")
    println("=" ^ 60)
    println("Parquet dir: $parquet_dir")
    println("Min observations: $min_obs")
    println("Threads: $(Threads.nthreads())")
    
    # Load all data
    println("\nLoading data...")
    load_start = time()
    df = load_parquet_dir(parquet_dir)
    println("  Loaded $(nrow(df)) rows in $(round(time() - load_start, digits=1))s")
    
    # Get entity counts
    count_start = time()
    entity_counts = get_entity_counts(df)
    println("  Counting took $(round(time() - count_start, digits=1))s")
    
    # Split by threshold
    entities_to_train = [e for (e, c) in entity_counts if c >= min_obs]
    entities_fallback = [e for (e, c) in entity_counts if c < min_obs]
    
    println("\nEntities with >= $min_obs ACTUAL: $(length(entities_to_train))")
    println("Entities with < $min_obs ACTUAL: $(length(entities_fallback)) (82% ratio)")
    
    # Create or load matched pairs
    local matched_df
    if !skip_matching || !isfile(matched_pairs_path)
        match_start = time()
        matched_df = create_matched_pairs(df, matched_pairs_path)
        println("  Matching took $(round(time() - match_start, digits=1))s")
    else
        println("\nLoading existing matched pairs...")
        matched_df = DataFrame(Parquet2.Dataset(matched_pairs_path))
    end
    
    # Train models
    println("\n" * "=" ^ 60)
    println("TRAINING $(length(entities_to_train)) ENTITY MODELS")
    println("=" ^ 60)
    
    train_start = time()
    successful = 0
    failed = 0
    
    # Note: Julia threading for XGBoost can be tricky
    # Using serial for stability, but XGBoost itself uses threads internally
    for (i, entity) in enumerate(entities_to_train)
        result, msg = train_single_entity(entity, matched_df, models_dir, 100)
        
        if result !== nothing
            successful += 1
        else
            failed += 1
            # println("  $entity: $msg")
        end
        
        if i % 20 == 0
            println("  Trained $i/$(length(entities_to_train)) models...")
        end
    end
    
    elapsed = time() - train_start
    
    println("\n" * "=" ^ 60)
    println("TRAINING COMPLETE")
    println("=" ^ 60)
    println("Successful: $successful")
    println("Failed: $failed")
    println("Training time: $(round(elapsed, digits=1))s ($(round(elapsed/length(entities_to_train), digits=2))s per entity)")
    println("Models saved to: $models_dir")
    
    return successful, elapsed
end

# Run if called directly
if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
