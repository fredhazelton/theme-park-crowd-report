# Theme Park Crowd Report Pipeline — Linux Compatibility Changes

*Analysis completed: 2026-01-28*

---

## Summary

The pipeline is **mostly cross-platform** thanks to Python's `pathlib` usage, but there are several **Windows-specific elements** that need Linux equivalents.

| Category | Severity | Items |
|----------|----------|-------|
| Scripts | 🔴 High | 6 PowerShell scripts need bash equivalents |
| Scheduled Tasks | 🔴 High | Windows Task Scheduler → cron/systemd |
| Hardcoded Paths | 🟡 Medium | Default paths reference `D:\` and Windows Python |
| Documentation | 🟢 Low | README examples all use PowerShell/Windows |

---

## 🔴 HIGH PRIORITY

### 1. PowerShell Scripts → Bash

These `.ps1` scripts need bash (`.sh`) equivalents:

| Windows Script | Purpose | Linux Equivalent Needed |
|----------------|---------|------------------------|
| `scripts/run_queue_times_loop.ps1` | Continuous queue-times fetch | `run_queue_times_loop.sh` |
| `scripts/run_dimension_fetches.ps1` | Fetch all dimension tables | `run_dimension_fetches.sh` |
| `scripts/register_scheduled_tasks.ps1` | Register Windows tasks | `install_cron.sh` or systemd units |
| `scripts/register_log_cleanup_task.ps1` | Log cleanup task | Include in cron setup |
| `scripts/stream_deck_queue_times.ps1` | Stream Deck integration | `stream_deck_queue_times.sh` |

Also: `scripts/start_queue_times_stream_deck.bat` → not needed on Linux

### 2. Windows Task Scheduler → Cron/Systemd

Current scheduled tasks (from README):
- **5 AM ET** — Main ETL (`get_tp_wait_time_data_from_s3.py`)
- **5:30 AM ET** — Posted accuracy report
- **6 AM ET** — Dimension fetch (`run_dimension_fetches.ps1`)
- **7 AM ET** — Secondary ETL run
- **Sunday** — Log cleanup, posted accuracy report

**Linux options:**
1. **Cron jobs** — Simple, traditional
2. **Systemd timers** — Modern, better logging
3. **Supervisor + cron** — For the continuous queue-times loop

Example cron (EST timezone):
```cron
0 5 * * * cd /path/to/repo && python src/get_tp_wait_time_data_from_s3.py >> logs/etl.log 2>&1
0 6 * * * cd /path/to/repo && ./scripts/run_dimension_fetches.sh >> logs/dimensions.log 2>&1
0 7 * * * cd /path/to/repo && python src/get_tp_wait_time_data_from_s3.py >> logs/etl.log 2>&1
```

### 3. Hardcoded Windows Python Path

In `scripts/train_batch_entities.py` (line 194):
```python
default=r"C:\Users\fred\AppData\Local\Programs\Python\Python311\python.exe"
```

**Fix:** Change to `default="python"` or `default=sys.executable`

---

## 🟡 MEDIUM PRIORITY

### 4. Default Output Base Path

In `src/utils/paths.py`:
```python
_DEFAULT_OUTPUT_BASE = Path(
    r"D:\Dropbox (TouringPlans.com)\stats team\pipeline\hazeydata\theme-park-crowd-report"
)
```

**Options:**
1. Change default to a Linux-friendly path: `~/hazeydata/pipeline` or `/var/data/hazeydata`
2. Make it platform-aware:
```python
import platform
if platform.system() == "Windows":
    _DEFAULT_OUTPUT_BASE = Path(r"D:\Dropbox...")
else:
    _DEFAULT_OUTPUT_BASE = Path.home() / "hazeydata" / "pipeline"
```
3. **Best:** Require `config/config.json` and remove hardcoded default

### 5. PowerShell Scripts Default Paths

In `scripts/run_queue_times_loop.ps1`:
```powershell
$DefaultOutputBase = "D:\Dropbox (TouringPlans.com)\stats team\..."
```

The bash equivalents should read from `config/config.json` only.

### 6. Config Example

`config/config.example.json` has Windows paths:
```json
"output_base": "D:\\Dropbox..."
```

**Add Linux example:**
```json
"output_base": "/home/user/hazeydata/pipeline"
```

---

## 🟢 LOW PRIORITY (Documentation)

### 7. README.md

- All examples use `.\venv\Scripts\Activate.ps1` → Add `source venv/bin/activate`
- All `--output-base` examples use `D:\` paths → Add Linux examples
- "Windows Task Scheduler" section → Add "Linux (cron/systemd)" section

### 8. scripts/README.md

- Heavy PowerShell focus → Add bash equivalents documentation

---

## Python Code — Already Cross-Platform ✅

These are **already fine**:
- Uses `pathlib.Path` throughout (handles path separators)
- No Windows-specific imports in core logic
- `subprocess` calls are generic (just `python`, not `.exe`)
- SQLite, pandas, boto3 all work on Linux

---

## Recommended Implementation Order

1. **Create `config/config.json`** with Linux output path
2. **Write bash equivalents** for the 3 key scripts:
   - `run_queue_times_loop.sh`
   - `run_dimension_fetches.sh`  
   - `install_cron.sh`
3. **Fix hardcoded Python path** in `train_batch_entities.py`
4. **Test core ETL scripts** — should work as-is with config set
5. **Set up cron jobs** for scheduled runs
6. **Update documentation** with Linux instructions

---

## Quick Test (Should Work Now)

With a proper `config/config.json`, these should already work:
```bash
cd /path/to/theme-park-crowd-report
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set your output base
cp config/config.example.json config/config.json
# Edit config.json with Linux path

# Test dimension fetch
python src/get_entity_table_from_s3.py

# Test main ETL (requires AWS creds)
python src/get_tp_wait_time_data_from_s3.py
```

---

*Analysis by Wilma*
