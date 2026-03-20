# Alternative ML Approaches for TPCR Live Inference

**Date:** 2026-03-19  
**Current Status:** XGBoost-based model, MAE 6.6, bias +0.5 (32 days)  
**Research Goal:** Explore modern ML approaches to improve accuracy and reduce dependencies  

## Current Architecture Analysis

### Existing XGBoost Model
- **Features:** 7 features (posted_time, entity_encoded, park_encoded, hour_of_day, mins_since_6am, mins_since_open, date_group_id_encoded, season_encoded)
- **Task:** Regression (POSTED wait time → ACTUAL wait time)
- **Performance:** MAE 6.6 minutes, bias +0.5 minutes
- **Limitation:** XGBoost dependency, potential overfitting to limited features

### Target Improvements
1. **Accuracy:** Reduce MAE from 6.6 to <5.0 minutes
2. **Dependency:** Remove XGBoost requirement, use built-in libraries
3. **Interpretability:** Better understanding of adjustment factors
4. **Adaptability:** Handle new attractions/parks without retraining

## Alternative Approaches to Research

### 1. Ensemble of Simple Models ⭐⭐⭐⭐⭐
**Concept:** Combine multiple simple models instead of one complex XGBoost
- **Linear regression** for time-of-day patterns
- **Park-specific bias correction** (mean adjustments by entity)
- **Seasonal adjustment** factors
- **Recent history** (last N observations for same entity)

**Advantages:**
- No external dependencies (sklearn/numpy only)
- Highly interpretable
- Fast inference
- Easy to update individual components

**Implementation Plan:**
```python
class EnsembleLiveInference:
    def __init__(self):
        self.base_model = LinearRegression()  # Basic posted->actual
        self.park_adjustments = {}  # Per-park bias corrections
        self.time_adjustments = {}  # Hour-of-day patterns
        self.entity_adjustments = {}  # Per-attraction corrections
        self.seasonal_factors = {}  # Monthly/seasonal multipliers
        
    def predict(self, entity_code, posted_time, observed_at):
        # Base prediction
        base = self.base_model.predict([[posted_time]])[0]
        
        # Apply corrections
        park_adj = self.park_adjustments.get(entity_code[:6], 0)
        time_adj = self.time_adjustments.get(observed_at.hour, 0)
        entity_adj = self.entity_adjustments.get(entity_code, 0)
        seasonal = self.seasonal_factors.get(observed_at.month, 1.0)
        
        return base * seasonal + park_adj + time_adj + entity_adj
```

### 2. Neural Network with Embeddings ⭐⭐⭐⭐
**Concept:** Simple feedforward network with entity embeddings
- **Entity embeddings** learned from historical data
- **Time embeddings** (hour, day of week, season)
- **2-3 hidden layers** with ReLU activation
- **Dropout** for regularization

**Advantages:**
- Can learn complex non-linear patterns
- Entity embeddings capture attraction-specific behaviors
- Pytorch/TensorFlow available
- Better handling of categorical features

**Research Focus:**
- Optimal embedding dimensions
- Architecture depth vs performance
- Training stability with limited data

### 3. Physics-Informed Models ⭐⭐⭐⭐⭐
**Concept:** Incorporate theme park domain knowledge into model structure
- **Capacity constraints:** Model queue capacity limits
- **Flow dynamics:** In-flow vs out-flow relationships
- **Operating patterns:** Peak hours, show schedules
- **Weather impact:** External factors

**Example Constraints:**
```python
# Physical constraints in loss function
def physics_informed_loss(predicted, actual, capacity_limit):
    base_loss = mse(predicted, actual)
    
    # Constraint: predicted time can't exceed capacity-based maximum
    capacity_violation = max(0, predicted - capacity_limit)
    
    # Constraint: negative wait times are impossible
    negative_violation = max(0, -predicted)
    
    return base_loss + λ1 * capacity_violation + λ2 * negative_violation
```

**Research Questions:**
- Can we model queue capacity limits?
- How do operational patterns affect wait time accuracy?
- What domain constraints improve predictions?

### 4. Time Series Forecasting Approach ⭐⭐⭐
**Concept:** Treat each attraction as a time series, predict ACTUAL from POSTED sequence
- **ARIMA/SARIMA** for seasonal patterns
- **Prophet** for trend decomposition
- **LSTM** for sequence learning
- **Kalman filters** for state estimation

**Advantages:**
- Naturally handles temporal patterns
- Can incorporate external factors (weather, events)
- Good for capturing long-term trends

**Challenges:**
- Requires historical sequences (not just single observations)
- More complex inference pipeline
- May be overkill for real-time adjustment

### 5. Bayesian Approaches ⭐⭐⭐⭐
**Concept:** Probabilistic model with uncertainty quantification
- **Gaussian Process** regression
- **Bayesian linear regression** with priors
- **Variational inference** for complex posteriors

**Advantages:**
- Natural uncertainty quantification
- Can incorporate prior knowledge about wait times
- Robust to outliers
- No point estimates - full distributions

**Research Application:**
```python
# Bayesian model with domain-informed priors
model = BayesianWaitTimeModel(
    prior_adjustment_mean=0,  # Expect no systematic bias
    prior_adjustment_std=10,  # But allow ±10 min variations
    capacity_prior=(60, 120), # Most rides 60-120 min max
    seasonal_variance_prior=5  # Seasonal effects ~5 min
)
```

## Feature Engineering Research

### Advanced Features to Test
1. **Queue momentum:** Rate of change in recent posted times
2. **Park congestion:** Average wait across all attractions
3. **Weather correlation:** Temperature, precipitation impact
4. **Event detection:** Special events, holidays, crowd surges
5. **Attraction similarity:** Group similar rides for better inference
6. **Time-to-close:** How behavior changes near park closing
7. **Weekday vs weekend** patterns
8. **Historical accuracy:** How often has this attraction been accurate?

### Feature Selection Research
- **Correlation analysis** with ACTUAL adjustments
- **Mutual information** for non-linear relationships
- **SHAP values** for feature importance
- **Recursive feature elimination**

## Experimental Design

### Phase 1: Baseline Implementation (This Session)
1. Implement simple ensemble model (no external deps)
2. Test against historical POSTED→ACTUAL data
3. Compare accuracy with XGBoost baseline
4. Document performance differences

### Phase 2: Advanced Approaches (Next Sessions)
1. Neural network with embeddings (PyTorch)
2. Physics-informed constraints
3. Bayesian uncertainty quantification
4. Time series forecasting elements

### Phase 3: Production Integration
1. A/B testing framework
2. Online learning capabilities
3. Model monitoring and drift detection
4. Automated retraining pipelines

## Success Metrics

### Primary (Accuracy)
- **MAE improvement:** Target <5.0 minutes (vs current 6.6)
- **Bias reduction:** Target ±0.2 minutes (vs current +0.5)
- **RMSE improvement:** Include variance considerations

### Secondary (Operational)
- **Inference latency:** <10ms per prediction
- **Memory footprint:** <100MB model size
- **Dependency reduction:** Minimal external requirements
- **Interpretability:** Explainable predictions

### Robustness
- **New attraction handling:** Zero-shot prediction capability
- **Seasonal adaptation:** Performance across different time periods
- **Outlier resistance:** Graceful handling of anomalous data

## Research Tools & Datasets

### Historical Data Sources
- `fact_tables/parquet/*.parquet` - ACTUAL vs POSTED comparisons
- `staging/queue_times/` - Recent observations
- External: Weather data, park calendars, event schedules

### Experimentation Framework
```python
# Unified evaluation framework
class ModelComparison:
    def evaluate_model(self, model, test_data):
        predictions = model.predict_batch(test_data)
        return {
            'mae': mean_absolute_error(test_data.actual, predictions),
            'rmse': root_mean_squared_error(test_data.actual, predictions),
            'bias': mean(predictions - test_data.actual),
            'latency_ms': measure_inference_time(model, test_data),
            'interpretability_score': calculate_shap_coherence(model)
        }
```

## Implementation Roadmap

### Today (Research Session)
- [ ] Analyze current XGBoost model architecture
- [ ] Implement simple ensemble baseline
- [ ] Test against available historical data
- [ ] Document baseline performance

### This Week
- [ ] Physics-informed model prototype
- [ ] Neural network with embeddings
- [ ] Feature engineering experiments

### Next Month
- [ ] Bayesian approach implementation
- [ ] Time series forecasting integration
- [ ] Production deployment framework
- [ ] A/B testing infrastructure

---

**Key Insight:** The current MAE 6.6 suggests significant room for improvement. Theme park wait times have strong domain-specific patterns (capacity limits, operational schedules, crowd behaviors) that can be leveraged for better predictions beyond generic ML approaches.

**Next Action:** Implement ensemble baseline to establish improvement potential.