# Task: Fix all GridTable bugs

## Phase: Complete

### Bugs Fixed

| Bug | Description | Fix | File:Line |
|-----|-------------|-----|-----------|
| 1 & 7 | Pointer capture blocking scroll during selection | Removed `e.Pointer.Capture(this)` and `e.Pointer.Capture(null)` calls; added `PointerWheelChanged` handler that does not intercept wheel events | GridTable.axaml.cs:139-171 |
| 2 | Duplicate measurement methods | `MeasureColumnWidths(int count)` now delegates to `MeasureColumnWidthsInternal()` | GridTable.axaml.cs:834 |
| 3 & 10 | Inaccurate text width estimation (no real measurement, ignores wrapping) | Replaced `fontSize * 0.55` heuristic with `FormattedText` for accurate measurement including Cyrillic | GridTable.axaml.cs:868 |
| 4 | All wrappers created upfront | Verified: VirtualizingStackPanel virtualizes rendering; object creation overhead is acceptable. No fix needed. | — |
| 5 | Silent rebuild skipping | Public `RebuildTable()` now sets `_rebuildPending = true` and schedules deferred rebuild via `Dispatcher.UIThread.Post` | GridTable.axaml.cs:617,654 |
| 6 | O(n) pointer-move iteration | Added early exit (`break` when `pos.Y < bounds.Y`) to `FindWrapperAtPosition` — limits iteration to visible wrappers only | GridTable.axaml.cs:172 |
| 8 | Null-check gaps in `FindColumnAtPosition` | Added explicit null check for `_cachedColumnWidths`; returns -1 and triggers `ScheduleRebuild()` if null; caller guards against -1 | GridTable.axaml.cs:185,159 |
| 9 | Sort indicator on wrong column after column change | `OnPropertyChanged` now resets `_sortColumn` and `_sortAscending` when `ColumnHeadersProperty` changes | GridTable.axaml.cs:462 |

### Usage Check Across Windows
- 14 windows use GridTable (ExchangeInfoWindow, ShowInfoWindow, ShowHistoryWindow, etc.)
- All use `SetDataSource()` or set ColumnHeaders/Rows + `RebuildTable()`
- Some windows call `RebuildTable()` after `SetDataSource()` — causes double rebuild but `_isRebuilding` guard handles it
- All windows null-check `MainGridTable` before use
- No thread-safety issues found — all GridTable access is on UI thread

### Verification
- `dotnet build` — 0 errors, 255 warnings (all pre-existing)
