from pathlib import Path
from datetime import datetime
import json
import pandas as pd
from mcp.server.fastmcp import FastMCP

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
REPORTS = BASE / 'reports'
DATA.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)

mcp = FastMCP('Excel Analyst')


def workbook_path(filename: str) -> Path:
    """Resolve an Excel filename within the approved data directory."""
    path = (DATA / filename).resolve()
    if path.parent != DATA.resolve() or path.suffix.lower() != '.xlsx':
        raise ValueError('Use an .xlsx filename from the data folder.')
    if not path.is_file():
        raise FileNotFoundError(f'Workbook not found: {filename}')
    return path


def load_sheet(filename: str, sheet: str | None = None) -> pd.DataFrame:
    path = workbook_path(filename)
    frame = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0)
    if frame.empty:
        raise ValueError('This worksheet is empty.')
    frame.columns = frame.columns.map(str)
    if not frame.columns.is_unique:
        raise ValueError('Duplicate column names are not supported.')
    return frame


def clean(obj):
    """Make Pandas values safe for MCP JSON results."""
    return json.loads(json.dumps(obj, default=str, allow_nan=False))


def rows(frame: pd.DataFrame, limit: int = 10) -> list[dict]:
    return json.loads(frame.head(limit).to_json(orient='records', date_format='iso'))


@mcp.tool()
def list_excel_files() -> list[str]:
    """List available .xlsx files in the approved data directory."""
    return sorted(p.name for p in DATA.glob('*.xlsx') if p.is_file())


@mcp.tool()
def inspect_excel(filename: str, sheet: str | None = None) -> dict:
    """Show workbook sheet names, selected sheet columns, row count, and five sample rows."""
    path = workbook_path(filename)
    book = pd.ExcelFile(path)
    if sheet is not None and sheet not in book.sheet_names:
        raise ValueError(f'Unknown sheet. Available: {book.sheet_names}')
    frame = load_sheet(filename, sheet)
    return {
        'file': filename,
        'sheets': book.sheet_names,
        'selected_sheet': sheet or book.sheet_names[0],
        'row_count': len(frame),
        'columns': list(frame.columns),
        'sample': rows(frame, 5),
    }


@mcp.tool()
def analyze_excel(
    filename: str,
    column: str,
    operation: str = 'sum',
    group_by: str | None = None,
    sheet: str | None = None,
) -> dict:
    """Calculate sum, mean, min, max, or count for a column; optionally group by another column."""
    frame = load_sheet(filename, sheet)
    if column not in frame.columns:
        raise ValueError(f'Unknown column: {column}. Available: {list(frame.columns)}')
    if operation not in {'sum', 'mean', 'min', 'max', 'count'}:
        raise ValueError('Operation must be sum, mean, min, max, or count.')
    if group_by is not None and group_by not in frame.columns:
        raise ValueError(f'Unknown group column: {group_by}')
    if operation == 'count':
        series = frame[column]
    else:
        series = pd.to_numeric(frame[column], errors='coerce')
        if series.notna().sum() == 0:
            raise ValueError(f'No numeric values found in {column}.')
    if group_by is None:
        value = getattr(series, operation)()
        return {'operation': operation, 'column': column, 'result': clean(value.item() if hasattr(value, 'item') else value)}
    result = pd.DataFrame({'group': frame[group_by].fillna('Unknown').astype(str), 'value': series})
    grouped = getattr(result.groupby('group')['value'], operation)().dropna()
    grouped = grouped.sort_values(ascending=False).head(50)
    return {'operation': operation, 'column': column, 'group_by': group_by,
            'results': [{'group': str(k), 'value': clean(v.item() if hasattr(v, 'item') else v)} for k, v in grouped.items()]}


@mcp.tool()
def filter_excel(
    filename: str,
    column: str,
    value: str,
    sheet: str | None = None,
    limit: int = 30,
) -> dict:
    """Filter Excel rows where a column contains text (case insensitive); return at most 100 rows."""
    frame = load_sheet(filename, sheet)
    if column not in frame.columns:
        raise ValueError(f'Unknown column: {column}')
    limit = max(1, min(limit, 100))
    matches = frame[frame[column].astype(str).str.contains(value, case=False, regex=False, na=False)]
    return {'matching_rows': len(matches), 'returned_rows': min(len(matches), limit), 'rows': rows(matches, limit)}


@mcp.tool()
def top_excel_rows(
    filename: str,
    numeric_column: str,
    highest: bool = True,
    limit: int = 5,
    sheet: str | None = None,
) -> dict:
    """Return rows with the highest or lowest values in a numeric Excel column."""
    frame = load_sheet(filename, sheet)
    if numeric_column not in frame.columns:
        raise ValueError(f'Unknown column: {numeric_column}')
    values = pd.to_numeric(frame[numeric_column], errors='coerce')
    if values.notna().sum() == 0:
        raise ValueError('No numeric values in this column.')
    limit = max(1, min(limit, 50))
    selected = values.dropna().sort_values(ascending=not highest).head(limit).index
    return {'sort_column': numeric_column, 'highest': highest, 'rows': rows(frame.loc[selected], limit)}


@mcp.tool()
def export_excel_report(
    filename: str,
    column: str,
    operation: str = 'sum',
    group_by: str | None = None,
    sheet: str | None = None,
) -> dict:
    """Create a new Excel report in reports/ containing the requested aggregate results."""
    analysis = analyze_excel(filename, column, operation, group_by, sheet)
    if group_by is None:
        output = pd.DataFrame([{'Column': column, 'Operation': operation, 'Result': analysis['result']}])
    else:
        output = pd.DataFrame(analysis['results'])
        output.columns = ['Group', 'Value']
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    destination = REPORTS / f'report_{stamp}.xlsx'
    output.to_excel(destination, index=False)
    return {'report_path': str(destination), 'rows': len(output), 'source_file': filename}


if __name__ == '__main__':
    mcp.run(transport='stdio')
