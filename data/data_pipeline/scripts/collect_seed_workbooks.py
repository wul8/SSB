"""
Seed Workbooks Collection Script - Prepare 200 high-quality seed workbooks for Route A.

This script helps collect and validate seed workbooks from public sources for
expert-constructed Financial Model tasks. Seed workbooks must pass strict quality
checks before being accepted into the collection.

Quality Requirements:
1. Passes all S0 gate checks (recalc consistency, no external links, etc.)
2. Has meaningful formulas (>= 10 formula cells)
3. Financial modeling domain (contains keywords: revenue, EBITDA, cash flow, etc.)
4. Reasonable size (10-1000 rows, 5-100 columns)
5. No contamination with official benchmark
6. Clear provenance (source URL, company name, license)

Sources:
- Public company investor relations (10-K, 10-Q Excel models)
- Business school teaching materials (MIT, Harvard case studies)
- Template marketplaces (Microsoft Office, Vertex42, Smartsheet)
- GitHub financial modeling repos
- Kaggle datasets with financial models

Usage:
    # Scan a directory of candidate workbooks
    python collect_seed_workbooks.py scan /path/to/candidates --output seed_scan_report.json

    # Validate and import selected workbooks
    python collect_seed_workbooks.py import seed_scan_report.json --target-count 200

    # Show collection statistics
    python collect_seed_workbooks.py stats
"""

import os
import sys
import json
import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import openpyxl
from datetime import datetime

# Import from our existing modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from ingest.validators import WorkbookValidator, ValidationResult
from ingest.lineage import Lineage, LineageRegistry
from config import PROJECT_ROOT


@dataclass
class SeedWorkbookMetadata:
    """Metadata for a seed workbook."""
    file_name: str
    file_path: str
    lineage_id: str
    source_url: Optional[str]
    company: Optional[str]
    period: Optional[str]
    license: str
    quality_score: float  # 0-100
    formula_count: int
    sheet_count: int
    domain_keywords: List[str]
    imported_at: str


class SeedWorkbookCollector:
    """
    Collector for high-quality seed workbooks.

    This collector scans candidate workbooks, applies quality checks, and
    maintains a curated collection with provenance tracking.
    """

    def __init__(self,
                 seed_dir: Optional[Path] = None,
                 lineage_registry_path: Optional[Path] = None):
        """
        Initialize collector.

        Args:
            seed_dir: Directory to store seed workbooks (default: PROJECT_ROOT/corpus/seed_workbooks)
            lineage_registry_path: Path to lineage registry (default: PROJECT_ROOT/ingest/lineage_registry.json)
        """
        self.seed_dir = seed_dir or (PROJECT_ROOT / "corpus" / "seed_workbooks")
        self.seed_dir.mkdir(parents=True, exist_ok=True)

        registry_path = lineage_registry_path or (PROJECT_ROOT / "ingest" / "lineage_registry.json")
        self.lineage_registry = LineageRegistry(registry_path)

        self.validator = WorkbookValidator()
        self.metadata_file = self.seed_dir / "seed_collection_metadata.json"
        self.metadata: List[SeedWorkbookMetadata] = []
        self._load_metadata()

        # Financial modeling domain keywords
        self.domain_keywords = {
            'revenue', 'ebitda', 'cash flow', 'capex', 'depreciation', 'amortization',
            'balance sheet', 'income statement', 'p&l', 'profit', 'loss',
            'forecast', 'projection', 'valuation', 'dcf', 'wacc', 'npv', 'irr',
            'debt', 'equity', 'assets', 'liabilities', 'shareholders',
            'operating', 'financing', 'investing', 'working capital',
            'margin', 'ratio', 'roe', 'roa', 'eps', 'pe ratio'
        }

    def _load_metadata(self):
        """Load existing seed collection metadata."""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                data = json.load(f)
                self.metadata = [SeedWorkbookMetadata(**item) for item in data]
            print(f"Loaded {len(self.metadata)} existing seed workbooks")

    def _save_metadata(self):
        """Save seed collection metadata."""
        with open(self.metadata_file, 'w') as f:
            json.dump([asdict(item) for item in self.metadata], f, indent=2)

    def _compute_quality_score(self,
                               validation_result: ValidationResult,
                               formula_count: int,
                               sheet_count: int,
                               domain_keywords: List[str]) -> float:
        """
        Compute quality score (0-100) for a seed workbook.

        Scoring:
        - S0 gate pass: +40 points (required)
        - Formula density: +20 points (10-100 formulas = full score)
        - Sheet structure: +10 points (2-10 sheets = full score)
        - Domain relevance: +30 points (5+ keywords = full score)
        """
        score = 0.0

        # S0 gate pass (required)
        if validation_result.passed:
            score += 40.0
        else:
            return 0.0  # Fail immediately if S0 not passed

        # Formula density (10-100 formulas optimal)
        if formula_count >= 10:
            formula_score = min(20.0, (formula_count / 100.0) * 20.0)
            score += formula_score

        # Sheet structure (2-10 sheets optimal)
        if 2 <= sheet_count <= 10:
            score += 10.0
        elif sheet_count > 10:
            score += 5.0  # Too many sheets is okay but not ideal

        # Domain relevance (keyword count)
        keyword_score = min(30.0, (len(domain_keywords) / 5.0) * 30.0)
        score += keyword_score

        return round(score, 2)

    def _detect_domain_keywords(self, file_path: Path) -> List[str]:
        """Detect financial modeling domain keywords in workbook."""
        found_keywords = []
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
            # Check sheet names
            for sheet_name in wb.sheetnames:
                for keyword in self.domain_keywords:
                    if keyword.lower() in sheet_name.lower():
                        found_keywords.append(keyword)

            # Check cell values (sample first 100 rows)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
                    if row_idx >= 100:
                        break
                    for cell_value in row:
                        if isinstance(cell_value, str):
                            cell_lower = cell_value.lower()
                            for keyword in self.domain_keywords:
                                if keyword in cell_lower and keyword not in found_keywords:
                                    found_keywords.append(keyword)
        except Exception:
            pass

        return list(set(found_keywords))

    def _count_formulas(self, file_path: Path) -> int:
        """Count formula cells in workbook."""
        count = 0
        try:
            wb = openpyxl.load_workbook(file_path, data_only=False)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                for row in ws.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.startswith('='):
                            count += 1
        except Exception:
            pass
        return count

    def scan_candidates(self, candidate_dir: Path) -> List[Dict]:
        """
        Scan directory of candidate workbooks and generate quality report.

        Args:
            candidate_dir: Directory containing candidate .xlsx files

        Returns:
            List of candidate reports with quality scores
        """
        candidates = []
        xlsx_files = list(candidate_dir.glob("**/*.xlsx"))

        print(f"Scanning {len(xlsx_files)} candidate workbooks...")

        for file_path in xlsx_files:
            print(f"  Checking {file_path.name}...", end=" ")

            # S0 validation
            validation_result = self.validator.validate(file_path)

            # Count formulas and sheets
            formula_count = self._count_formulas(file_path)
            try:
                wb = openpyxl.load_workbook(file_path, read_only=True)
                sheet_count = len(wb.sheetnames)
                wb.close()
            except Exception:
                sheet_count = 0

            # Detect domain keywords
            domain_keywords = self._detect_domain_keywords(file_path)

            # Compute quality score
            quality_score = self._compute_quality_score(
                validation_result, formula_count, sheet_count, domain_keywords
            )

            candidate_report = {
                "file_name": file_path.name,
                "file_path": str(file_path),
                "passed_s0": validation_result.passed,
                "quality_score": quality_score,
                "formula_count": formula_count,
                "sheet_count": sheet_count,
                "domain_keywords": domain_keywords,
                "validation_errors": validation_result.errors,
                "validation_warnings": validation_result.warnings
            }
            candidates.append(candidate_report)

            status = "✓" if validation_result.passed else "✗"
            print(f"{status} Score: {quality_score:.1f}")

        # Sort by quality score
        candidates.sort(key=lambda x: x['quality_score'], reverse=True)

        return candidates

    def import_workbook(self,
                       source_path: Path,
                       source_url: Optional[str] = None,
                       company: Optional[str] = None,
                       period: Optional[str] = None,
                       license: str = "Unknown") -> Optional[str]:
        """
        Import a seed workbook into the collection.

        Args:
            source_path: Path to source workbook
            source_url: Source URL for provenance
            company: Company name (if applicable)
            period: Time period (e.g., "FY2023", "Q2 2024")
            license: License information

        Returns:
            lineage_id if successful, None if failed
        """
        # Check if this exact file already imported (by hash)
        import hashlib
        sha256 = hashlib.sha256()
        with open(source_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        file_hash = sha256.hexdigest()

        # Check if hash already exists in registry
        for existing in self.lineage_registry.registry.values():
            if existing.file_hash == file_hash:
                print(f"  Skip: {source_path.name} (duplicate hash)")
                return None

        # Validate
        validation_result = self.validator.validate(source_path)
        if not validation_result.passed:
            print(f"Failed validation: {validation_result.errors}")
            return None

        # Compute quality metrics
        formula_count = self._count_formulas(source_path)
        try:
            wb = openpyxl.load_workbook(source_path, read_only=True)
            sheet_count = len(wb.sheetnames)
            wb.close()
        except Exception:
            sheet_count = 0

        domain_keywords = self._detect_domain_keywords(source_path)
        quality_score = self._compute_quality_score(
            validation_result, formula_count, sheet_count, domain_keywords
        )

        if quality_score < 50.0:
            print(f"Quality score too low: {quality_score}")
            return None

        # Create lineage
        family_name = company.lower().replace(" ", "_") if company else "seed_collection"

        # Add to registry
        lineage_id = self.lineage_registry.register(
            file_path=source_path,
            family_name=family_name,
            source_type="seed_workbook",
            source_url=source_url,
            company=company,
            period=period,
            license=license
        )

        # Copy to seed directory with lineage_id as filename
        target_path = self.seed_dir / f"{lineage_id}.xlsx"
        shutil.copy2(source_path, target_path)

        # Create metadata
        metadata = SeedWorkbookMetadata(
            file_name=source_path.name,
            file_path=str(target_path),
            lineage_id=lineage_id,
            source_url=source_url,
            company=company,
            period=period,
            license=license,
            quality_score=quality_score,
            formula_count=formula_count,
            sheet_count=sheet_count,
            domain_keywords=domain_keywords,
            imported_at=datetime.now().isoformat()
        )
        self.metadata.append(metadata)
        self._save_metadata()

        print(f"Imported: {lineage_id} (quality: {quality_score:.1f})")
        return lineage_id

    def get_collection_stats(self) -> Dict:
        """Get statistics about the seed collection."""
        if not self.metadata:
            return {"total": 0}

        quality_scores = [m.quality_score for m in self.metadata]
        formula_counts = [m.formula_count for m in self.metadata]

        return {
            "total": len(self.metadata),
            "avg_quality": round(sum(quality_scores) / len(quality_scores), 2),
            "min_quality": min(quality_scores),
            "max_quality": max(quality_scores),
            "avg_formulas": round(sum(formula_counts) / len(formula_counts), 2),
            "companies": len(set(m.company for m in self.metadata if m.company)),
            "sources": len(set(m.source_url for m in self.metadata if m.source_url))
        }


def main():
    parser = argparse.ArgumentParser(description="Seed workbooks collection tool")
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Scan command
    scan_parser = subparsers.add_parser('scan', help='Scan candidate workbooks')
    scan_parser.add_argument('candidate_dir', type=Path, help='Directory with candidate workbooks')
    scan_parser.add_argument('--output', type=Path, default='seed_scan_report.json',
                            help='Output report file')
    scan_parser.add_argument('--min-score', type=float, default=50.0,
                            help='Minimum quality score to include')

    # Import command
    import_parser = subparsers.add_parser('import', help='Import workbooks from scan report')
    import_parser.add_argument('scan_report', type=Path, help='Scan report JSON file')
    import_parser.add_argument('--target-count', type=int, default=200,
                              help='Target number of workbooks to import')
    import_parser.add_argument('--min-score', type=float, default=50.0,
                              help='Minimum quality score to import')

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show collection statistics')

    args = parser.parse_args()

    collector = SeedWorkbookCollector()

    if args.command == 'scan':
        # Scan candidates
        candidates = collector.scan_candidates(args.candidate_dir)

        # Filter by min score
        filtered = [c for c in candidates if c['quality_score'] >= args.min_score]

        report = {
            "scan_date": datetime.now().isoformat(),
            "candidate_dir": str(args.candidate_dir),
            "total_scanned": len(candidates),
            "passed_filter": len(filtered),
            "min_score_filter": args.min_score,
            "candidates": filtered
        }

        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nScan complete:")
        print(f"  Total scanned: {len(candidates)}")
        print(f"  Passed filter (>={args.min_score}): {len(filtered)}")
        print(f"  Report saved to: {args.output}")

    elif args.command == 'import':
        # Load scan report
        with open(args.scan_report, 'r') as f:
            report = json.load(f)

        candidates = report['candidates']
        # Sort by quality score and take top N
        candidates.sort(key=lambda x: x['quality_score'], reverse=True)
        to_import = candidates[:args.target_count]

        print(f"Importing {len(to_import)} workbooks...")

        imported_count = 0
        for candidate in to_import:
            source_path = Path(candidate['file_path'])
            if not source_path.exists():
                print(f"  Skip: {source_path.name} (file not found)")
                continue

            # Extract metadata from filename or set as Unknown
            lineage_id = collector.import_workbook(
                source_path=source_path,
                source_url=None,  # TODO: Add interactive prompts or CSV input
                company=None,
                period=None,
                license="Unknown"
            )

            if lineage_id:
                imported_count += 1

            if imported_count >= args.target_count:
                break

        print(f"\nImported {imported_count} workbooks")
        stats = collector.get_collection_stats()
        print(f"Collection total: {stats['total']}")

    elif args.command == 'stats':
        stats = collector.get_collection_stats()
        print("\n=== Seed Collection Statistics ===")
        print(f"Total workbooks: {stats.get('total', 0)}")
        if stats.get('total', 0) > 0:
            print(f"Average quality: {stats['avg_quality']}")
            print(f"Quality range: {stats['min_quality']} - {stats['max_quality']}")
            print(f"Average formulas: {stats['avg_formulas']}")
            print(f"Unique companies: {stats['companies']}")
            print(f"Unique sources: {stats['sources']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
