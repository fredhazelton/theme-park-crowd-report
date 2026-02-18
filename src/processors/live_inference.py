"""
Live Inference Model for Real-Time POSTED->ACTUAL Conversion

================================================================================
PURPOSE
================================================================================
Provides a fast, real-time inference engine for converting POSTED wait times
to predicted ACTUAL wait times. Optimized for low-latency prediction on live
queue-times data.

Key features:
- Loads model + metadata + dimension lookups once at initialization
- Keeps everything in memory for fast inference
- Handles unknown entities gracefully with fallback methods
- Batch prediction support for efficiency
- No disk I/O after initialization

================================================================================
ARCHITECTURE
================================================================================
Uses a simplified feature set (7 features) that can be computed entirely from:
- entity_code (attraction identifier)
- posted_time (posted wait time in minutes)
- observed_at (datetime of observation)

Features derived at inference:
- posted_time (direct input)
- entity_encoded (from entity_code lookup)
- park_encoded (from entity_code first 2 chars)
- hour_of_day (from observed_at)
- mins_since_6am (from observed_at)
- mins_since_open (from park hours lookup)
- date_group_id_encoded (from date lookup)
- season_encoded (from date lookup)

================================================================================
USAGE
================================================================================
  # Initialize model (loads everything into memory)
  model = LiveInferenceModel(output_base)
  
  # Single prediction
  result = model.predict("WDW-MK-BTM", 45.0, datetime.now())
  # Returns: {"predicted_actual": 38, "entity_code": "WDW-MK-BTM", 
  #          "posted_time": 45, "adjustment": -7, "method": "live_model"}
  
  # Batch prediction
  observations = [
      {"entity_code": "WDW-MK-BTM", "posted_time": 45.0, "observed_at": datetime.now()},
      {"entity_code": "WDW-EP-EX", "posted_time": 60.0, "observed_at": datetime.now()},
  ]
  results = model.predict_batch(observations)
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd

from utils.park_code import entity_code_to_park_code
import numpy as np
from zoneinfo import ZoneInfo

try:
    import xgboost as xgb
except ImportError:
    xgb = None


class LiveInferenceModel:
    """Fast in-memory live inference model for POSTED->ACTUAL conversion."""
    
    def __init__(self, output_base: Union[str, Path]):
        """
        Initialize the live inference model.
        
        Loads model, metadata, and all required dimension tables into memory
        for fast inference without disk I/O.
        
        Args:
            output_base: Path to pipeline output directory
        """
        if xgb is None:
            raise ImportError("XGBoost not installed")
        
        self.output_base = Path(output_base)
        
        # Load model and metadata
        model_dir = self.output_base / "models" / "_live_inference"
        model_path = model_dir / "model.json"
        metadata_path = model_dir / "metadata.json"
        
        if not model_path.exists():
            raise FileNotFoundError(f"Live inference model not found: {model_path}")
        
        self.model = xgb.Booster()
        self.model.load_model(str(model_path))
        
        with open(metadata_path, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        
        self.feature_names = self.metadata['feature_names']
        self.encodings = self.metadata['encodings']
        
        # Load dimension tables into memory
        self._load_dimension_tables()
        
        # Load fallback ratios for unknown entities
        self._load_fallback_ratios()
        
        # Load entity-specific ratios for 100-499 pair tier
        self._load_entity_ratios()
        
        print(f"✅ Live inference model loaded:")
        print(f"   Model: {model_path}")
        print(f"   Features: {len(self.feature_names)}")
        print(f"   Entities: {len(self.encodings['entity_code'])}")
        print(f"   Parks: {len(self.encodings['park_code'])}")
        if self.entity_ratios:
            print(f"   Entity-ratio tier: {len(self.entity_ratios)} entities")
    
    def _load_entity_ratios(self):
        """Load entity-specific ratios for 100-499 pair tier."""
        ratios_path = self.output_base / "models" / "_live_inference" / "entity_ratios.json"
        if ratios_path.exists():
            with open(ratios_path, "r", encoding="utf-8") as f:
                self.entity_ratios = json.load(f)
        else:
            self.entity_ratios = {}
            print(f"⚠️  Entity ratios file not found: {ratios_path}")
    
    def _load_dimension_tables(self):
        """Load all dimension tables into memory for fast lookup."""
        dim_dir = self.output_base / "dimension_tables"
        
        # Load park hours
        parkhours_path = dim_dir / "dimparkhours.csv"
        if parkhours_path.exists():
            ph_df = pd.read_csv(parkhours_path)
            ph_df['date'] = pd.to_datetime(ph_df['date']).dt.date
            ph_df['park'] = ph_df['park'].str.upper()
            
            # Convert opening_time to minutes since midnight for fast calculation
            ph_df['opening_minutes'] = pd.to_datetime(ph_df['opening_time'], utc=True).dt.hour * 60 + \
                                      pd.to_datetime(ph_df['opening_time'], utc=True).dt.minute
            
            # Create lookup dict: (park, date) -> opening_minutes
            self.park_hours = {}
            for _, row in ph_df.iterrows():
                self.park_hours[(row['park'], row['date'])] = row['opening_minutes']
        else:
            self.park_hours = {}
            print(f"⚠️  Park hours file not found: {parkhours_path}")
        
        # Load date group IDs
        dg_path = dim_dir / "dimdategroupid.csv"
        if dg_path.exists():
            dg_df = pd.read_csv(dg_path)
            dg_df['park_date'] = pd.to_datetime(dg_df['park_date']).dt.date
            
            # Create lookup dict: date -> date_group_id
            self.date_group_ids = {}
            for _, row in dg_df.iterrows():
                self.date_group_ids[row['park_date']] = str(row['date_group_id'])
        else:
            self.date_group_ids = {}
            print(f"⚠️  Date group ID file not found: {dg_path}")
        
        # Load seasons
        season_path = dim_dir / "dimseason.csv"
        if season_path.exists():
            season_df = pd.read_csv(season_path)
            season_df['park_date'] = pd.to_datetime(season_df['park_date']).dt.date
            
            # Create lookup dict: date -> season
            self.seasons = {}
            for _, row in season_df.iterrows():
                self.seasons[row['park_date']] = row['season']
        else:
            self.seasons = {}
            print(f"⚠️  Season file not found: {season_path}")
    
    def _load_fallback_ratios(self):
        """Load fallback ratios for unknown entities."""
        fallback_path = self.output_base / "state" / "fallback_ratios.json"
        if fallback_path.exists():
            with open(fallback_path, "r") as f:
                self.fallback_ratios = json.load(f)
        else:
            # Default fallback ratios if file doesn't exist
            self.fallback_ratios = {
                "WDW-MK": 0.85,  # Magic Kingdom
                "WDW-EP": 0.88,  # EPCOT
                "WDW-HS": 0.83,  # Hollywood Studios
                "WDW-AK": 0.87,  # Animal Kingdom
                "DL-DL": 0.84,   # Disneyland
                "DL-CA": 0.86,   # California Adventure
                "global": 0.86   # Overall fallback
            }
            print(f"⚠️  Fallback ratios file not found: {fallback_path}, using defaults")
    
    def _extract_features(self, entity_code: str, posted_time: float, observed_at: datetime) -> Dict[str, float]:
        """Extract all features needed for inference from the three inputs."""
        
        # Basic features
        features = {
            "posted_time": posted_time,
            "hour_of_day": observed_at.hour,
            "mins_since_6am": (observed_at.hour - 6) * 60 + observed_at.minute,
        }
        
        # Park code from entity code (handles TDL, TDS, USH correctly)
        park_code = entity_code_to_park_code(entity_code) or "XX"
        
        # Entity encoding
        if entity_code in self.encodings['entity_code']:
            features["entity_encoded"] = self.encodings['entity_code'][entity_code]
        else:
            # Use unknown entity encoding (max + 1)
            features["entity_encoded"] = max(self.encodings['entity_code'].values()) + 1
        
        # Park encoding  
        if park_code in self.encodings['park_code']:
            features["park_encoded"] = self.encodings['park_code'][park_code]
        else:
            # Use unknown park encoding (max + 1)
            features["park_encoded"] = max(self.encodings['park_code'].values()) + 1
        
        # Date-based features
        obs_date = observed_at.date()
        
        # Minutes since park open
        park_key = (park_code, obs_date)
        if park_key in self.park_hours:
            opening_minutes = self.park_hours[park_key]
            current_minutes = observed_at.hour * 60 + observed_at.minute
            features["mins_since_open"] = current_minutes - opening_minutes
        else:
            # Fallback to mins_since_6am if no park hours
            features["mins_since_open"] = features["mins_since_6am"]
        
        # Date group ID encoding
        if obs_date in self.date_group_ids:
            date_group_id = self.date_group_ids[obs_date]
            if date_group_id in self.encodings['date_group_id']:
                features["date_group_id_encoded"] = self.encodings['date_group_id'][date_group_id]
            else:
                features["date_group_id_encoded"] = max(self.encodings['date_group_id'].values()) + 1
        else:
            features["date_group_id_encoded"] = max(self.encodings['date_group_id'].values()) + 1
        
        # Season encoding
        if obs_date in self.seasons:
            season = self.seasons[obs_date]
            if season in self.encodings['season']:
                features["season_encoded"] = self.encodings['season'][season]
            else:
                features["season_encoded"] = max(self.encodings['season'].values()) + 1
        else:
            features["season_encoded"] = max(self.encodings['season'].values()) + 1
        
        return features
    
    def _get_fallback_prediction(self, entity_code: str, posted_time: float) -> float:
        """Get fallback prediction using ratio method for unknown entities."""
        
        # Try park-specific ratio first
        park_code = entity_code_to_park_code(entity_code) or "XX"
        park_key = f"WDW-{park_code[4:]}" if park_code.startswith("WDW") else f"DL-{park_code[3:]}" if park_code.startswith("DL") else park_code
        
        if park_key in self.fallback_ratios:
            ratio = self.fallback_ratios[park_key]
        else:
            ratio = self.fallback_ratios.get("global", 0.86)
        
        return posted_time * ratio
    
    def predict(self, entity_code: str, posted_time: float, observed_at: datetime) -> Dict:
        """
        Predict ACTUAL wait time for a single observation.
        
        Args:
            entity_code: Entity code (e.g., "WDW-MK-BTM")
            posted_time: Posted wait time in minutes
            observed_at: Observation datetime
        
        Returns:
            Dictionary with prediction results:
            {
                "predicted_actual": int,
                "entity_code": str,
                "posted_time": int,
                "adjustment": int,
                "method": "live_model" | "entity_ratio" | "fallback_ratio"
            }
        """
        
        # 1. Entity-specific ratio tier (100-499 pairs) — use simple ratio before model
        if entity_code in self.entity_ratios:
            ratio = self.entity_ratios[entity_code]
            prediction = posted_time * ratio
            method = "entity_ratio"
        else:
            # 2. Check if entity can use the trained model
            can_use_model = (
                entity_code in self.encodings['entity_code'] and
                observed_at.date() in self.date_group_ids and
                observed_at.date() in self.seasons
            )
            
            if can_use_model:
                try:
                    features = self._extract_features(entity_code, posted_time, observed_at)
                    feature_vector = [features[name] for name in self.feature_names]
                    dmatrix = xgb.DMatrix([feature_vector], feature_names=self.feature_names)
                    prediction = self.model.predict(dmatrix)[0]
                    prediction = max(0, min(300, prediction))
                    method = "live_model"
                except Exception:
                    prediction = self._get_fallback_prediction(entity_code, posted_time)
                    method = "fallback_ratio"
            else:
                prediction = self._get_fallback_prediction(entity_code, posted_time)
                method = "fallback_ratio"
        
        predicted_actual = int(round(prediction))
        adjustment = predicted_actual - int(posted_time)
        
        return {
            "predicted_actual": predicted_actual,
            "entity_code": entity_code,
            "posted_time": int(posted_time),
            "adjustment": adjustment,
            "method": method
        }
    
    def predict_batch(self, observations: List[Dict]) -> List[Dict]:
        """
        Predict ACTUAL wait times for multiple observations efficiently.
        
        Args:
            observations: List of dicts with keys: entity_code, posted_time, observed_at
        
        Returns:
            List of prediction result dictionaries
        """
        results = []
        
        # Group observations by method (entity_ratio vs model vs fallback)
        entity_ratio_obs = []
        model_obs = []
        fallback_obs = []
        
        for i, obs in enumerate(observations):
            entity_code = obs['entity_code']
            observed_at = obs['observed_at']
            
            if entity_code in self.entity_ratios:
                entity_ratio_obs.append((i, obs))
            elif (
                entity_code in self.encodings['entity_code'] and
                observed_at.date() in self.date_group_ids and
                observed_at.date() in self.seasons
            ):
                model_obs.append((i, obs))
            else:
                fallback_obs.append((i, obs))
        
        # Process model-based predictions in batch
        if model_obs:
            try:
                # Extract features for all model observations
                feature_matrix = []
                for _, obs in model_obs:
                    features = self._extract_features(obs['entity_code'], obs['posted_time'], obs['observed_at'])
                    feature_vector = [features[name] for name in self.feature_names]
                    feature_matrix.append(feature_vector)
                
                # Batch prediction
                dmatrix = xgb.DMatrix(feature_matrix, feature_names=self.feature_names)
                predictions = self.model.predict(dmatrix)
                
                # Process results
                for (i, obs), prediction in zip(model_obs, predictions):
                    prediction = max(0, min(300, prediction))
                    predicted_actual = int(round(prediction))
                    adjustment = predicted_actual - int(obs['posted_time'])
                    
                    results.append((i, {
                        "predicted_actual": predicted_actual,
                        "entity_code": obs['entity_code'],
                        "posted_time": int(obs['posted_time']),
                        "adjustment": adjustment,
                        "method": "live_model"
                    }))
                    
            except Exception:
                # If batch fails, move to fallback
                for i, obs in model_obs:
                    fallback_obs.append((i, obs))
                model_obs = []
        
        # Process entity_ratio tier (100-499 pairs)
        for i, obs in entity_ratio_obs:
            ratio = self.entity_ratios[obs['entity_code']]
            prediction = obs['posted_time'] * ratio
            predicted_actual = int(round(prediction))
            adjustment = predicted_actual - int(obs['posted_time'])
            results.append((i, {
                "predicted_actual": predicted_actual,
                "entity_code": obs['entity_code'],
                "posted_time": int(obs['posted_time']),
                "adjustment": adjustment,
                "method": "entity_ratio"
            }))
        
        # Process fallback predictions
        for i, obs in fallback_obs:
            prediction = self._get_fallback_prediction(obs['entity_code'], obs['posted_time'])
            predicted_actual = int(round(prediction))
            adjustment = predicted_actual - int(obs['posted_time'])
            
            results.append((i, {
                "predicted_actual": predicted_actual,
                "entity_code": obs['entity_code'],
                "posted_time": int(obs['posted_time']),
                "adjustment": adjustment,
                "method": "fallback_ratio"
            }))
        
        # Sort results back to original order and return
        results.sort(key=lambda x: x[0])
        return [result[1] for result in results]


def load_live_inference_model(output_base: Union[str, Path]) -> LiveInferenceModel:
    """Convenience function to load the live inference model."""
    return LiveInferenceModel(output_base)