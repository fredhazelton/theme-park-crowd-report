#!/usr/bin/env python3
"""
Systematic Bias Correction Framework

Analyzes prediction bias patterns at park and entity level, then applies
corrections to improve forecast accuracy. Addresses persistent over/under-prediction
patterns identified in accuracy drift monitoring.

Usage:
    python scripts/bias_correction_framework.py --mode analyze
    python scripts/bias_correction_framework.py --mode correct --target-date 2026-03-08
    python scripts/bias_correction_framework.py --mode evaluate --days 30
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Ensure src is in path for utilities
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.park_code import entity_code_to_park_code

# Configuration
OUTPUT_BASE = Path("/mnt/data/pipeline")
BIAS_OUTPUT_DIR = OUTPUT_BASE / "bias_correction"
ACCURACY_DIR = OUTPUT_BASE / "accuracy"
FORECAST_DIR = OUTPUT_BASE / "curves" / "forecast_parquet"

# Bias correction parameters
MIN_SAMPLES = 10  # Minimum samples needed for bias calculation
LOOKBACK_DAYS = 30  # Days to look back for bias calculation
BIAS_THRESHOLD = 2.0  # Minimum bias (minutes) to trigger correction
CONFIDENCE_THRESHOLD = 0.7  # Confidence level for bias correction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BiasAnalyzer:
    """Analyzes prediction bias patterns at park and entity levels."""
    
    def __init__(self):
        self.accuracy_data = None
        self.bias_patterns = {}
        
    def load_accuracy_data(self, lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
        """Load accuracy evaluation data for bias analysis."""
        accuracy_file = ACCURACY_DIR / "slot_accuracy.parquet"
        
        if not accuracy_file.exists():
            raise FileNotFoundError(f"Accuracy file not found: {accuracy_file}")
        
        # Load accuracy data
        df = pd.read_parquet(accuracy_file)
        
        # Filter to lookback period
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)
        
        # Convert park_date to date if it's not already
        if df['park_date'].dtype == 'object':
            df['park_date'] = pd.to_datetime(df['park_date']).dt.date
        
        # Filter by date range
        mask = (df['park_date'] >= start_date) & (df['park_date'] <= end_date)
        self.accuracy_data = df[mask].copy()
        
        # Add bias column for convenience
        self.accuracy_data['bias'] = self.accuracy_data['forecast_wait'] - self.accuracy_data['actual_wait']
        
        logger.info(f"Loaded {len(self.accuracy_data)} accuracy records from {accuracy_file}")
        logger.info(f"Date range: {self.accuracy_data['park_date'].min()} to {self.accuracy_data['park_date'].max()}")
        
        return self.accuracy_data
    
    def analyze_park_bias(self) -> Dict[str, Dict]:
        """Analyze bias patterns at the park level."""
        if self.accuracy_data is None:
            raise ValueError("Must call load_accuracy_data() first")
        
        # Calculate bias by park
        park_bias = {}
        
        for entity_code in self.accuracy_data['entity_code'].unique():
            park_code = entity_code_to_park_code(entity_code)
            entity_data = self.accuracy_data[self.accuracy_data['entity_code'] == entity_code]
            
            if len(entity_data) >= MIN_SAMPLES:
                bias = entity_data['bias'].mean()
                bias_std = entity_data['bias'].std()
                mae = entity_data['absolute_error'].mean()
                
                if park_code not in park_bias:
                    park_bias[park_code] = {
                        'entities': [],
                        'total_bias': 0,
                        'total_samples': 0,
                        'bias_values': []
                    }
                
                park_bias[park_code]['entities'].append({
                    'entity_code': entity_code,
                    'bias': bias,
                    'bias_std': bias_std,
                    'mae': mae,
                    'samples': len(entity_data),
                    'confidence': self._calculate_confidence(bias, bias_std, len(entity_data))
                })
                
                park_bias[park_code]['total_samples'] += len(entity_data)
                park_bias[park_code]['bias_values'].extend(entity_data['bias'].tolist())
        
        # Calculate park-level statistics
        for park_code in park_bias:
            bias_values = park_bias[park_code]['bias_values']
            park_bias[park_code]['park_bias'] = np.mean(bias_values)
            park_bias[park_code]['park_bias_std'] = np.std(bias_values)
            park_bias[park_code]['park_mae'] = np.mean(np.abs(bias_values))
            park_bias[park_code]['park_confidence'] = self._calculate_confidence(
                np.mean(bias_values), 
                np.std(bias_values), 
                len(bias_values)
            )
            
            # Clean up intermediate data
            del park_bias[park_code]['bias_values']
        
        self.bias_patterns['park'] = park_bias
        return park_bias
    
    def analyze_entity_bias(self) -> Dict[str, Dict]:
        """Analyze bias patterns at the individual entity level."""
        if self.accuracy_data is None:
            raise ValueError("Must call load_accuracy_data() first")
        
        entity_bias = {}
        
        for entity_code in self.accuracy_data['entity_code'].unique():
            entity_data = self.accuracy_data[self.accuracy_data['entity_code'] == entity_code]
            
            if len(entity_data) >= MIN_SAMPLES:
                bias = entity_data['bias'].mean()
                bias_std = entity_data['bias'].std()
                mae = entity_data['absolute_error'].mean()
                
                # Time-based bias analysis - extract hour from time_slot
                entity_data_time = entity_data.copy()
                # Handle time_slot which might be a time object already
                if entity_data_time['time_slot'].dtype == 'object':
                    try:
                        entity_data_time['hour'] = pd.to_datetime(entity_data_time['time_slot'], format='%H:%M:%S').dt.hour
                    except:
                        entity_data_time['hour'] = entity_data_time['time_slot'].apply(
                            lambda x: x.hour if hasattr(x, 'hour') else pd.to_datetime(str(x)).hour
                        )
                else:
                    entity_data_time['hour'] = pd.to_datetime(entity_data_time['time_slot']).dt.hour
                hourly_bias = entity_data_time.groupby('hour')['bias'].mean().to_dict()
                
                entity_bias[entity_code] = {
                    'park_code': entity_code_to_park_code(entity_code),
                    'overall_bias': bias,
                    'bias_std': bias_std,
                    'mae': mae,
                    'samples': len(entity_data),
                    'confidence': self._calculate_confidence(bias, bias_std, len(entity_data)),
                    'hourly_bias': hourly_bias,
                    'needs_correction': abs(bias) >= BIAS_THRESHOLD and 
                                     self._calculate_confidence(bias, bias_std, len(entity_data)) >= CONFIDENCE_THRESHOLD
                }
        
        self.bias_patterns['entity'] = entity_bias
        return entity_bias
    
    def _calculate_confidence(self, bias: float, std: float, samples: int) -> float:
        """Calculate confidence level for bias correction based on sample size and consistency."""
        if samples < MIN_SAMPLES or std == 0:
            return 0.0
        
        # Confidence based on standard error and sample size
        se = std / np.sqrt(samples)
        t_stat = abs(bias) / se if se > 0 else 0
        
        # Simple confidence calculation (could be improved with proper t-distribution)
        confidence = min(t_stat / 3.0, 1.0)  # Normalize roughly
        confidence *= min(samples / 50.0, 1.0)  # Boost with sample size
        
        return confidence
    
    def generate_correction_factors(self) -> Dict[str, float]:
        """Generate correction factors for entities that need bias correction."""
        if 'entity' not in self.bias_patterns:
            raise ValueError("Must run analyze_entity_bias() first")
        
        correction_factors = {}
        
        for entity_code, bias_info in self.bias_patterns['entity'].items():
            if bias_info['needs_correction']:
                # Simple correction: subtract the bias
                correction_factors[entity_code] = -bias_info['overall_bias']
                
                logger.info(f"Generated correction factor for {entity_code}: "
                          f"{correction_factors[entity_code]:.2f} minutes "
                          f"(bias: {bias_info['overall_bias']:.2f}, "
                          f"confidence: {bias_info['confidence']:.2f})")
        
        return correction_factors
    
    def save_analysis(self, output_dir: Optional[Path] = None) -> None:
        """Save bias analysis results to JSON files."""
        output_dir = output_dir or BIAS_OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save park-level analysis
        if 'park' in self.bias_patterns:
            park_file = output_dir / f"park_bias_analysis_{timestamp}.json"
            with open(park_file, 'w') as f:
                json.dump(self.bias_patterns['park'], f, indent=2, default=str)
            logger.info(f"Saved park bias analysis to {park_file}")
        
        # Save entity-level analysis
        if 'entity' in self.bias_patterns:
            entity_file = output_dir / f"entity_bias_analysis_{timestamp}.json"
            with open(entity_file, 'w') as f:
                json.dump(self.bias_patterns['entity'], f, indent=2, default=str)
            logger.info(f"Saved entity bias analysis to {entity_file}")
        
        # Save correction factors
        correction_factors = self.generate_correction_factors()
        if correction_factors:
            correction_file = output_dir / f"bias_correction_factors_{timestamp}.json"
            with open(correction_file, 'w') as f:
                json.dump(correction_factors, f, indent=2, default=str)
            logger.info(f"Saved {len(correction_factors)} correction factors to {correction_file}")


class BiasCorrector:
    """Applies bias corrections to forecast data."""
    
    def __init__(self, correction_factors: Dict[str, float]):
        self.correction_factors = correction_factors
    
    def correct_forecasts(self, target_date: date) -> None:
        """Apply bias corrections to forecasts for a specific date."""
        forecast_file = FORECAST_DIR / "all_forecasts.parquet"
        
        if not forecast_file.exists():
            raise FileNotFoundError(f"Forecast file not found: {forecast_file}")
        
        # Load forecasts
        forecasts = pd.read_parquet(forecast_file)
        logger.info(f"Loaded {len(forecasts)} forecast records")
        
        # Filter for target date
        date_forecasts = forecasts[forecasts['park_date'] == target_date]
        if len(date_forecasts) == 0:
            logger.warning(f"No forecasts found for {target_date}")
            return
        
        logger.info(f"Found {len(date_forecasts)} forecasts for {target_date}")
        
        # Apply corrections
        corrections_applied = 0
        for entity_code, correction in self.correction_factors.items():
            entity_mask = date_forecasts['entity_code'] == entity_code
            if entity_mask.sum() > 0:
                # Apply correction to predicted_actual
                forecasts.loc[
                    (forecasts['park_date'] == target_date) & 
                    (forecasts['entity_code'] == entity_code),
                    'predicted_actual'
                ] += correction
                
                corrections_applied += entity_mask.sum()
                logger.info(f"Applied {correction:.2f} min correction to {entity_code} "
                          f"({entity_mask.sum()} records)")
        
        if corrections_applied > 0:
            # Save corrected forecasts
            backup_file = forecast_file.with_suffix('.parquet.pre_bias_correction')
            if not backup_file.exists():
                forecast_file.rename(backup_file)
                logger.info(f"Created backup: {backup_file}")
            
            forecasts.to_parquet(forecast_file, index=False)
            logger.info(f"Applied bias corrections to {corrections_applied} forecast records")
        else:
            logger.info("No corrections were applied (no matching entities)")


def main():
    # KILL SWITCH - BIAS CORRECTION PERMANENTLY DISABLED 2026-03-21
    # Evidence: Bias correction caused 83% accuracy degradation (MAE 8.5 vs 1.5)
    # Decision: Fred Hazelton executive order to disable permanently
    print("🚨 BIAS CORRECTION SYSTEM PERMANENTLY DISABLED 🚨")
    print("Date: 2026-03-21")
    print("Reason: Caused 83% accuracy degradation")  
    print("Evidence: MAE 8.5 WITH correction vs 1.5 WITHOUT correction")
    print("Decision: Executive order to kill bias correction permanently")
    print("Contact: Fred Hazelton if you think this should be re-enabled")
    return 1  # Exit immediately

    parser = argparse.ArgumentParser(description="Systematic Bias Correction Framework")
    parser.add_argument("--mode", required=True, 
                       choices=["analyze", "correct", "evaluate"],
                       help="Mode: analyze bias, correct forecasts, or evaluate corrections")
    parser.add_argument("--target-date", type=str,
                       help="Target date for correction (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS,
                       help="Days to look back for analysis")
    parser.add_argument("--output-dir", type=str,
                       help="Output directory for analysis files")
    
    args = parser.parse_args()
    
    if args.mode == "analyze":
        analyzer = BiasAnalyzer()
        
        try:
            analyzer.load_accuracy_data(lookback_days=args.days)
            park_bias = analyzer.analyze_park_bias()
            entity_bias = analyzer.analyze_entity_bias()
            
            # Print summary
            print("\n=== BIAS ANALYSIS SUMMARY ===")
            print(f"\nPark-level bias patterns ({len(park_bias)} parks):")
            for park_code, info in sorted(park_bias.items()):
                direction = "over-predicting" if info['park_bias'] > 0 else "under-predicting"
                print(f"  {park_code}: {direction} by {abs(info['park_bias']):.2f} min "
                      f"(confidence: {info['park_confidence']:.2f}, "
                      f"{len(info['entities'])} entities)")
            
            # Entities needing correction
            entities_needing_correction = [
                (code, info) for code, info in entity_bias.items() 
                if info['needs_correction']
            ]
            
            print(f"\nEntities needing correction ({len(entities_needing_correction)}):")
            for entity_code, info in sorted(entities_needing_correction, 
                                          key=lambda x: abs(x[1]['overall_bias']), 
                                          reverse=True):
                direction = "over-predicting" if info['overall_bias'] > 0 else "under-predicting"
                print(f"  {entity_code} ({info['park_code']}): {direction} by "
                      f"{abs(info['overall_bias']):.2f} min "
                      f"(confidence: {info['confidence']:.2f})")
            
            output_dir = Path(args.output_dir) if args.output_dir else None
            analyzer.save_analysis(output_dir)
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return 1
    
    elif args.mode == "correct":
        if not args.target_date:
            print("--target-date required for correction mode")
            return 1
        
        try:
            target_date = datetime.strptime(args.target_date, "%Y-%m-%d").date()
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD")
            return 1
        
        # Load latest correction factors
        correction_files = list(BIAS_OUTPUT_DIR.glob("bias_correction_factors_*.json"))
        if not correction_files:
            print("No bias correction factors found. Run --mode analyze first.")
            return 1
        
        latest_file = max(correction_files, key=lambda p: p.stat().st_mtime)
        with open(latest_file) as f:
            correction_factors = json.load(f)
        
        print(f"Loaded {len(correction_factors)} correction factors from {latest_file}")
        
        corrector = BiasCorrector(correction_factors)
        corrector.correct_forecasts(target_date)
    
    elif args.mode == "evaluate":
        print("Evaluation mode not yet implemented")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())