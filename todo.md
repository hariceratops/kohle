## Roadmap

### Infrastructure
- [x] Autoflush

### Services
- [x] Query Transactions - Basic
- [x] Query Accounts
- [ ] Updates + Deletes design

### Model Updates
- [ ] Rename debit_categories to expenses
- [ ] Add time to Transactions

### Importing Statements
- [ ] Safe rollbacks

### UI-Model Interaction
- [ ] Convert record of strings to model and vice versa
- [ ] Controller protocol

### UI
- [ ] Refactor Spreadsheet/TableEditor code
- [ ] TreeTable?
- [ ] DialogBox

### Importer plugin
- [x] Plugin introduction
- [x] Example Deutsche Bank plugin
- [ ] Check for importer robustness
- [ ] Plugin as subprocess

### Asset 
- [ ] Modelling

### Catergorization
- [ ] Catergorization Engine
- [ ] Querying by category
- [ ] Category hierarchy?
- [ ] Budgetting

### Documentation
- [ ] Generate cli documentation automatically - sphinx / mkdocs + click

### App initialization
- [ ] Migration
- [ ] Mandatory configurations
- [ ] Check in top

### Deployment
- [ ] Git hooks for tests and documentation generation

## Open Points
### Return type of import use case
Instead of returning int. Return: inserted, duplicates

### Maintaining import history
Before parsing, sha256(file_bytes). If exists, abort immediately.
This gives you, O(1) duplicate detection.

ImportReport table
Track: file name, plugin, inserted, duplicates, duration

### Plugins metadata:
Return metadata. Plugins should describe themselves.
Example:
```python
class N26Plugin(StatementPlugin):
    name = "n26"
    version = "1.0"
    supported_formats = ["csv"]
```
Then:
```bash
kohle plugins --verbose
```
Outputs:
```bash
n26 (v1.0) — CSV export from N26 bank
```
