#!/usr/bin/env python3
"""
Ensemble Live Inference - Research Prototype

A research implementation of an ensemble-based approach for POSTED->ACTUAL
wait time prediction, designed to replace XGBoost with simpler, more
interpretable models that don't require external dependencies.

Key Features:
- Pure numpy/pandas implementation (no XGBoost/sklearn)
- Ensemble of simple models with different strengths
- Highly interpretable adjustments
- Fast inference suitable for production
- Handles unknown entities gracefully

Research Goals:
1. Match or exceed XGBoost MAE 6.6 performance
2. Provide interpretable adjustment factors
3. Reduce external dependencies
4. Handle new attractions without retraining
"""

from __future__ import annotations

import json
import pickle
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo


class SimpleLinearRegression:
    """Simple linear regression implementation without sklearn."""
    
    def __init__(self):
        self.slope = 0.0
        self.intercept = 0.0
        self.fitted = False
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Fit linear regression: y = slope * X + intercept"""
        if len(X) < 2:
            # Fallback for insufficient data
            self.slope = 1.0
            self.intercept = 0.0
            self.fitted = True
            return
        
        # Calculate slope and intercept using least squares
        X_mean = np.mean(X)
        y_mean = np.mean(y)
        
        numerator = np.sum((X - X_mean) * (y - y_mean))
        denominator = np.sum((X - X_mean) ** 2)
        
        if denominator == 0:
            self.slope = 1.0
            self.intercept = 0.0
        else:
            self.slope = numerator / denominator
            self.intercept = y_mean - self.slope * X_mean
        
        self.fitted = True
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict using fitted model."""
        if not self.fitted:
            raise ValueError("Model not fitted yet")
        
        return self.slope * X + self.intercept


class EnsembleLiveInference:
    """Ensemble-based live inference model for POSTED->ACTUAL conversion."""
    
    def __init__(self, output_base: Union[str, Path]):
        """Initialize ensemble model."""
        self.output_base = Path(output_base)
        
        # Core models in the ensemble
        self.base_model = SimpleLinearRegression()
        
        # Adjustment factors (learned from data)
        self.park_adjustments: Dict[str, float] = {}
        self.entity_adjustments: Dict[str, float] = {}
        self.hour_adjustments: Dict[int, float] = {}
        self.season_adjustments: Dict[int, float] = {}  # month-based
        self.capacity_limits: Dict[str, float] = {}
        
        # Recent history for momentum-based predictions
        self.recent_errors: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
        
        # Metadata
        self.feature_means = {}
        self.global_stats = {
            'mean_posted': 0.0,
            'mean_actual': 0.0,
            'mean_adjustment': 0.0,
            'std_adjustment': 1.0
        }
        
        self.fitted = False
    
    def _extract_features(self, entity_code: str, posted_time: float, observed_at: datetime) -> Dict[str, Union[float, int, str]]:
        """Extract features for prediction."""
        park_code = entity_code[:6] if len(entity_code) >= 6 else entity_code
        
        # Time-based features
        est_time = observed_at.astimezone(ZoneInfo("America/New_York"))
        hour = est_time.hour
        month = est_time.month
        weekday = est_time.weekday()  # 0=Monday, 6=Sunday
        
        # Calculate minutes since 6am
        hour_6am = est_time.replace(hour=6, minute=0, second=0, microsecond=0)
        if est_time.hour < 6:
            hour_6am -= timedelta(days=1)
        mins_since_6am = (est_time - hour_6am).total_seconds() / 60
        
        return {
            'entity_code': entity_code,
            'park_code': park_code,
            'posted_time': posted_time,
            'hour': hour,
            'month': month,
            'weekday': weekday,
            'mins_since_6am': mins_since_6am,
            'is_weekend': weekday >= 5,
            'observed_at': observed_at
        }
    
    def fit(self, training_data: pd.DataFrame) -> None:
        """
        Train the ensemble model on historical POSTED->ACTUAL data.
        
        Expected columns: entity_code, posted_time, actual_time, observed_at
        """
        print(f"Training ensemble model on {len(training_data):,} observations...")
        
        # Extract features for all training data
        features_list = []
        for _, row in training_data.iterrows():
            features = self._extract_features(
                row['entity_code'], 
                row['posted_time'], 
                pd.to_datetime(row['observed_at'])
            )
            features['actual_time'] = row['actual_time']
            features['adjustment'] = row['actual_time'] - row['posted_time']
            features_list.append(features)
        
        features_df = pd.DataFrame(features_list)
        
        # Global statistics
        self.global_stats = {
            'mean_posted': features_df['posted_time'].mean(),
            'mean_actual': features_df['actual_time'].mean(),
            'mean_adjustment': features_df['adjustment'].mean(),
            'std_adjustment': features_df['adjustment'].std()
        }
        
        print(f"Global stats: Posted={self.global_stats['mean_posted']:.1f}, Actual={self.global_stats['mean_actual']:.1f}, Adj={self.global_stats['mean_adjustment']:+.1f}±{self.global_stats['std_adjustment']:.1f}")
        
        # 1. Base model: Simple linear regression posted -> actual
        X = features_df['posted_time'].values
        y = features_df['actual_time'].values
        self.base_model.fit(X, y)
        
        print(f"Base model: y = {self.base_model.slope:.3f}x + {self.base_model.intercept:.1f}")
        
        # 2. Park-level adjustments (mean adjustment by park)
        park_adj = features_df.groupby('park_code')['adjustment'].agg(['mean', 'count'])
        for park, (mean_adj, count) in park_adj.iterrows():
            if count >= 5:  # Only use parks with sufficient data
                self.park_adjustments[park] = mean_adj
        
        print(f"Park adjustments learned: {len(self.park_adjustments)}")
        
        # 3. Entity-level adjustments (mean adjustment by entity, after park correction)
        entity_adj = features_df.groupby('entity_code')['adjustment'].agg(['mean', 'count'])
        for entity, (mean_adj, count) in entity_adj.iterrows():
            if count >= 3:  # Only use entities with sufficient data
                park_code = entity[:6]
                park_correction = self.park_adjustments.get(park_code, 0)
                entity_specific_adj = mean_adj - park_correction
                self.entity_adjustments[entity] = entity_specific_adj
        
        print(f"Entity adjustments learned: {len(self.entity_adjustments)}")
        
        # 4. Hour-of-day adjustments
        hour_adj = features_df.groupby('hour')['adjustment'].agg(['mean', 'count'])
        for hour, (mean_adj, count) in hour_adj.iterrows():
            if count >= 10:
                self.hour_adjustments[hour] = mean_adj
        
        print(f"Hour adjustments learned: {len(self.hour_adjustments)}")
        
        # 5. Seasonal (monthly) adjustments
        month_adj = features_df.groupby('month')['adjustment'].agg(['mean', 'count'])
        for month, (mean_adj, count) in month_adj.iterrows():
            if count >= 20:
                self.season_adjustments[month] = mean_adj
        
        print(f"Seasonal adjustments learned: {len(self.season_adjustments)}")
        
        # 6. Capacity limits (95th percentile of actual times by entity)
        capacity = features_df.groupby('entity_code')['actual_time'].quantile(0.95)
        for entity, limit in capacity.items():
            if limit > 0:
                self.capacity_limits[entity] = limit
        
        print(f"Capacity limits learned: {len(self.capacity_limits)}")
        
        self.fitted = True
        print("Ensemble model training complete!")
    
    def predict(self, entity_code: str, posted_time: float, observed_at: datetime) -> Dict[str, Union[str, float]]:
        """Make a single prediction."""
        if not self.fitted:
            raise ValueError("Model not fitted yet")
        
        features = self._extract_features(entity_code, posted_time, observed_at)
        
        # 1. Base prediction from linear model
        base_pred = self.base_model.predict(np.array([posted_time]))[0]
        
        # 2. Apply ensemble adjustments
        park_code = features['park_code']
        hour = features['hour']
        month = features['month']
        
        # Park adjustment
        park_adj = self.park_adjustments.get(park_code, 0.0)
        
        # Entity-specific adjustment
        entity_adj = self.entity_adjustments.get(entity_code, 0.0)
        
        # Hour-of-day adjustment
        hour_adj = self.hour_adjustments.get(hour, 0.0)
        
        # Seasonal adjustment
        seasonal_adj = self.season_adjustments.get(month, 0.0)
        
        # Combine adjustments (weighted by confidence/data availability)\n        adjustment_factors = [\n            ('base', 0.0, 1.0),  # Base model already includes overall trend\n            ('park', park_adj, 0.3),\n            ('entity', entity_adj, 0.4),\n            ('hour', hour_adj, 0.2),\n            ('seasonal', seasonal_adj, 0.1)\n        ]\n        \n        total_adjustment = sum(adj * weight for _, adj, weight in adjustment_factors)\n        \n        # Final prediction\n        predicted_actual = base_pred + total_adjustment\n        \n        # Apply capacity constraint (if known)\n        capacity_limit = self.capacity_limits.get(entity_code)\n        if capacity_limit and predicted_actual > capacity_limit * 1.1:  # Allow 10% over capacity\n            predicted_actual = capacity_limit * 1.1\n        \n        # Ensure non-negative prediction\n        predicted_actual = max(0.0, predicted_actual)\n        \n        # Calculate adjustment from posted time\n        adjustment = predicted_actual - posted_time\n        \n        # Determine prediction method\n        method_components = []\n        if entity_code in self.entity_adjustments:\n            method_components.append('entity')\n        if park_code in self.park_adjustments:\n            method_components.append('park')\n        if hour in self.hour_adjustments:\n            method_components.append('time')\n        \n        method = 'ensemble_' + '_'.join(method_components) if method_components else 'ensemble_base'\n        \n        return {\n            'entity_code': entity_code,\n            'posted_time': posted_time,\n            'predicted_actual': round(predicted_actual, 1),\n            'adjustment': round(adjustment, 1),\n            'method': method,\n            'base_pred': round(base_pred, 1),\n            'park_adj': round(park_adj, 1),\n            'entity_adj': round(entity_adj, 1),\n            'hour_adj': round(hour_adj, 1),\n            'seasonal_adj': round(seasonal_adj, 1)\n        }\n    \n    def predict_batch(self, observations: List[Dict[str, Union[str, float, datetime]]]) -> List[Dict[str, Union[str, float]]]:\n        \"\"\"Make batch predictions efficiently.\"\"\"\n        return [self.predict(obs['entity_code'], obs['posted_time'], obs['observed_at']) \n                for obs in observations]\n    \n    def evaluate(self, test_data: pd.DataFrame) -> Dict[str, float]:\n        \"\"\"Evaluate model performance on test data.\"\"\"\n        predictions = []\n        actuals = []\n        \n        for _, row in test_data.iterrows():\n            pred = self.predict(\n                row['entity_code'], \n                row['posted_time'], \n                pd.to_datetime(row['observed_at'])\n            )\n            predictions.append(pred['predicted_actual'])\n            actuals.append(row['actual_time'])\n        \n        predictions = np.array(predictions)\n        actuals = np.array(actuals)\n        \n        mae = np.mean(np.abs(predictions - actuals))\n        rmse = np.sqrt(np.mean((predictions - actuals) ** 2))\n        bias = np.mean(predictions - actuals)\n        \n        return {\n            'mae': mae,\n            'rmse': rmse,\n            'bias': bias,\n            'correlation': np.corrcoef(predictions, actuals)[0, 1] if len(predictions) > 1 else 0.0\n        }\n    \n    def save(self, path: Path) -> None:\n        \"\"\"Save model to disk.\"\"\"\n        model_data = {\n            'base_model': {\n                'slope': self.base_model.slope,\n                'intercept': self.base_model.intercept,\n                'fitted': self.base_model.fitted\n            },\n            'park_adjustments': self.park_adjustments,\n            'entity_adjustments': self.entity_adjustments,\n            'hour_adjustments': self.hour_adjustments,\n            'season_adjustments': self.season_adjustments,\n            'capacity_limits': self.capacity_limits,\n            'global_stats': self.global_stats,\n            'fitted': self.fitted\n        }\n        \n        path.parent.mkdir(parents=True, exist_ok=True)\n        with open(path, 'w') as f:\n            json.dump(model_data, f, indent=2)\n        \n        print(f\"Model saved to {path}\")\n    \n    def load(self, path: Path) -> None:\n        \"\"\"Load model from disk.\"\"\"\n        with open(path, 'r') as f:\n            model_data = json.load(f)\n        \n        # Restore base model\n        self.base_model.slope = model_data['base_model']['slope']\n        self.base_model.intercept = model_data['base_model']['intercept']\n        self.base_model.fitted = model_data['base_model']['fitted']\n        \n        # Restore adjustments\n        self.park_adjustments = model_data['park_adjustments']\n        self.entity_adjustments = model_data['entity_adjustments']\n        \n        # Convert hour keys back to integers (JSON serializes dict keys as strings)\n        self.hour_adjustments = {int(k): v for k, v in model_data['hour_adjustments'].items()}\n        self.season_adjustments = {int(k): v for k, v in model_data['season_adjustments'].items()}\n        \n        self.capacity_limits = model_data['capacity_limits']\n        self.global_stats = model_data['global_stats']\n        self.fitted = model_data['fitted']\n        \n        print(f\"Model loaded from {path}\")\n\n\ndef load_historical_data_for_training(output_base: Path) -> pd.DataFrame:\n    \"\"\"Load historical POSTED->ACTUAL data for training.\"\"\"\n    try:\n        import duckdb\n        \n        # Look for parquet files\n        fact_dir = output_base / \"fact_tables\" / \"parquet\"\n        \n        if not fact_dir.exists():\n            print(f\"No fact tables found at {fact_dir}\")\n            return pd.DataFrame()\n        \n        parquet_files = list(fact_dir.glob(\"*.parquet\"))\n        if not parquet_files:\n            print(f\"No parquet files found in {fact_dir}\")\n            return pd.DataFrame()\n        \n        print(f\"Loading training data from {len(parquet_files)} parquet files...\")\n        \n        con = duckdb.connect()\n        \n        # Find POSTED->ACTUAL pairs\n        query = f\"\"\"\n        WITH posted_data AS (\n            SELECT entity_code, observed_at, wait_time_minutes as posted_time\n            FROM read_parquet('{fact_dir}/*.parquet')\n            WHERE wait_time_type = 'POSTED'\n              AND wait_time_minutes IS NOT NULL\n              AND wait_time_minutes > 0\n        ),\n        actual_data AS (\n            SELECT entity_code, observed_at, wait_time_minutes as actual_time\n            FROM read_parquet('{fact_dir}/*.parquet')\n            WHERE wait_time_type = 'ACTUAL'\n              AND wait_time_minutes IS NOT NULL\n              AND wait_time_minutes > 0\n        )\n        SELECT \n            p.entity_code,\n            p.posted_time,\n            a.actual_time,\n            p.observed_at,\n            EXTRACT(epoch FROM (a.observed_at - p.observed_at))/60 as time_diff_minutes\n        FROM posted_data p\n        INNER JOIN actual_data a ON p.entity_code = a.entity_code\n        WHERE ABS(EXTRACT(epoch FROM (a.observed_at - p.observed_at))) <= 1800  -- Within 30 minutes\n        ORDER BY p.observed_at DESC\n        LIMIT 50000\n        \"\"\"\n        \n        df = con.execute(query).fetchdf()\n        con.close()\n        \n        if len(df) > 0:\n            print(f\"Loaded {len(df):,} POSTED->ACTUAL pairs for training\")\n            print(f\"Date range: {df['observed_at'].min()} to {df['observed_at'].max()}\")\n            print(f\"Entities: {df['entity_code'].nunique()}\")\n            return df\n        else:\n            print(\"No POSTED->ACTUAL pairs found\")\n            return pd.DataFrame()\n            \n    except Exception as e:\n        print(f\"Error loading historical data: {e}\")\n        return pd.DataFrame()\n\n\nif __name__ == \"__main__\":\n    # Test/demo the ensemble model\n    from pathlib import Path\n    import sys\n    \n    if len(sys.argv) > 1:\n        output_base = Path(sys.argv[1])\n    else:\n        output_base = Path(\"pipeline_dev\")\n    \n    print(\"=\"*60)\n    print(\"ENSEMBLE LIVE INFERENCE - RESEARCH PROTOTYPE\")\n    print(\"=\"*60)\n    print(f\"Output base: {output_base}\")\n    print()\n    \n    # Load training data\n    training_data = load_historical_data_for_training(output_base)\n    \n    if len(training_data) == 0:\n        print(\"No training data available. Cannot train model.\")\n        sys.exit(1)\n    \n    # Train model\n    model = EnsembleLiveInference(output_base)\n    model.fit(training_data)\n    \n    # Save model\n    model_path = output_base / \"models\" / \"ensemble_live_inference\" / \"model.json\"\n    model.save(model_path)\n    \n    # Evaluate on training data (for initial assessment)\n    print(\"\\nEvaluating on training data:\")\n    metrics = model.evaluate(training_data)\n    print(f\"MAE: {metrics['mae']:.2f} minutes\")\n    print(f\"RMSE: {metrics['rmse']:.2f} minutes\")\n    print(f\"Bias: {metrics['bias']:+.2f} minutes\")\n    print(f\"Correlation: {metrics['correlation']:.3f}\")\n    \n    # Test a few predictions\n    print(\"\\nSample predictions:\")\n    from datetime import datetime\n    from zoneinfo import ZoneInfo\n    \n    test_cases = [\n        (\"WDW-MK-BTM\", 45.0, datetime.now(ZoneInfo(\"America/New_York\"))),\n        (\"WDW-EP-EX\", 60.0, datetime.now(ZoneInfo(\"America/New_York\"))),\n        (\"DLR-DL-SM\", 30.0, datetime.now(ZoneInfo(\"America/Los_Angeles\")))\n    ]\n    \n    for entity, posted, timestamp in test_cases:\n        try:\n            result = model.predict(entity, posted, timestamp)\n            print(f\"{entity}: {posted} min -> {result['predicted_actual']} min ({result['adjustment']:+.1f}, {result['method']})\")\n        except Exception as e:\n            print(f\"{entity}: Error - {e}\")\n    \n    print(\"\\nResearch prototype complete!\")