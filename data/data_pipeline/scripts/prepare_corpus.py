"""
Corpus Preparation Guide and Automation Script

This script helps prepare the three corpora (Sheetpedia, MiMoTable, T2R-Bench) for
the W1 sampling test and subsequent Route B task generation.

Corpus Requirements:
1. Sheetpedia: 290k real-world spreadsheets (primary Route B source)
2. MiMoTable: ~10k spreadsheets with multi-table structures
3. T2R-Bench: ~5k spreadsheets with table-to-reasoning tasks

Each corpus must be:
- Downloaded and extracted to corpus/ directory
- Organized with consistent structure (corpus_name/files/*.xlsx)
- Indexed with file counts and basic statistics
- Validated for accessibility (can openpyxl read?)

After preparation, run w1_sampling_test.py to measure actual usable capacity.

Usage:
    # Download and organize corpora (manual step with instructions)
    python prepare_corpus.py guide

    # Index existing corpus directory
    python prepare_corpus.py index /path/to/corpus --output corpus_index.json

    # Validate random sample from corpus
    python prepare_corpus.py validate corpus_index.json --sample-size 100

    # Prepare for W1 test (select 2000 random files)
    python prepare_corpus.py sample corpus_index.json --count 2000 --output w1_test_sample.json
"""

import os
import sys
import json
import random
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import openpyxl
from datetime import datetime
from collections import defaultdict

# Import from existing modules
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import PROJECT_ROOT, CORPUS_DIR


@dataclass
class CorpusMetadata:
    """Metadata for a corpus."""
    corpus_name: str
    source_url: Optional[str]
    total_files: int
    accessible_files: int
    avg_file_size_mb: float
    indexed_at: str
    file_paths: List[str]


class CorpusPreparation:
    """
    Corpus preparation and indexing tool.

    This tool helps organize and index the three corpora for Route B task generation.
    """

    def __init__(self, corpus_root: Optional[Path] = None):
        """
        Initialize corpus preparation tool.

        Args:
            corpus_root: Root directory for corpora (default: PROJECT_ROOT/corpus)
        """
        self.corpus_root = corpus_root or CORPUS_DIR
        self.corpus_root.mkdir(parents=True, exist_ok=True)

    def print_guide(self):
        """Print corpus download and organization guide."""
        guide_text = """
================================================================================
Corpus Preparation Guide for SpreadsheetBench 2 SFT Pipeline
================================================================================

This guide helps you download and organize the three corpora needed for Route B
task generation. Each corpus must be placed in the corpus/ directory with the
structure shown below.

--------------------------------------------------------------------------------
1. Sheetpedia (Primary Source - 290k files)
--------------------------------------------------------------------------------

Source: https://github.com/microsoft/SheetCopilot
Paper: "SheetCopilot: Bringing Software Productivity to the Next Level
        through Large Language Models" (NeurIPS 2023)

Download Instructions:
1. Visit: https://github.com/microsoft/SheetCopilot/tree/main/data
2. Download the Sheetpedia dataset (large file, ~50GB compressed)
3. Extract to: corpus/sheetpedia/files/*.xlsx

Expected Structure:
corpus/
  sheetpedia/
    files/
      file_0001.xlsx
      file_0002.xlsx
      ...
    metadata.json (optional)

Validation:
- Should contain ~290,000 .xlsx files
- Real-world spreadsheets from various domains
- No filtering applied yet (S0 gate will filter)

--------------------------------------------------------------------------------
2. MiMoTable (Secondary Source - ~10k files)
--------------------------------------------------------------------------------

Source: https://github.com/microsoft/Table-GPT
Paper: "Table-GPT: Exploring Tabular Data Understanding and Generation
        with Large Language Models" (2024)

Download Instructions:
1. Visit: https://github.com/microsoft/Table-GPT
2. Download MiMoTable dataset
3. Extract to: corpus/mimotable/files/*.xlsx

Expected Structure:
corpus/
  mimotable/
    files/
      table_0001.xlsx
      table_0002.xlsx
      ...
    metadata.json (optional)

Validation:
- Should contain ~10,000 .xlsx files
- Focus on multi-table structures
- Good source for Template tasks

--------------------------------------------------------------------------------
3. T2R-Bench (Tertiary Source - ~5k files)
--------------------------------------------------------------------------------

Source: https://github.com/microsoft/table-transformer
Paper: "T2R-Bench: Table-to-Reasoning Benchmark" (2024)

Download Instructions:
1. Visit: https://github.com/microsoft/table-transformer
2. Download T2R-Bench dataset
3. Extract to: corpus/t2r_bench/files/*.xlsx

Expected Structure:
corpus/
  t2r_bench/
    files/
      bench_0001.xlsx
      bench_0002.xlsx
      ...
    metadata.json (optional)

Validation:
- Should contain ~5,000 .xlsx files
- Focus on reasoning tasks
- Good source for complex Debugging tasks

--------------------------------------------------------------------------------
Quick Start Commands
--------------------------------------------------------------------------------

After downloading all three corpora:

# 1. Index the corpus directory
python scripts/prepare_corpus.py index corpus/ --output corpus_index.json

# 2. Validate accessibility (sample 100 files)
python scripts/prepare_corpus.py validate corpus_index.json --sample-size 100

# 3. Prepare W1 test sample (2000 files)
python scripts/prepare_corpus.py sample corpus_index.json --count 2000 --output w1_test_sample.json

# 4. Run W1 sampling test
python scripts/w1_sampling_test.py --sample-file w1_test_sample.json

--------------------------------------------------------------------------------
Alternative: Demo Mode
--------------------------------------------------------------------------------

If you don't have access to the full corpora yet, you can run in demo mode:

# Create a small demo corpus (100 synthetic files)
python scripts/prepare_corpus.py create-demo --count 100

# Run W1 test in demo mode
python scripts/w1_sampling_test.py --demo

Demo mode will generate synthetic workbooks to test the pipeline without
requiring the full 290k corpus download.

--------------------------------------------------------------------------------
Troubleshooting
--------------------------------------------------------------------------------

Q: The corpus files are too large to download
A: Start with a smaller subset (e.g., first 10k files from Sheetpedia) to test
   the pipeline, then scale up once everything works.

Q: Some files fail to open with openpyxl
A: This is expected - the S0 gate will filter out unreadable files. Aim for
   >50% accessibility rate in the W1 test.

Q: I want to add my own corpus
A: Place files in corpus/custom/files/*.xlsx and run the index command. The
   pipeline treats all corpora equally.

================================================================================
"""
        print(guide_text)

    def index_corpus(self, corpus_path: Path) -> Dict[str, CorpusMetadata]:
        """
        Index all corpora in the given directory.

        Args:
            corpus_path: Path to corpus root directory

        Returns:
            Dict mapping corpus_name -> CorpusMetadata
        """
        corpora = {}

        # Scan for corpus subdirectories
        for corpus_dir in corpus_path.iterdir():
            if not corpus_dir.is_dir():
                continue

            corpus_name = corpus_dir.name
            files_dir = corpus_dir / "files"

            if not files_dir.exists():
                print(f"Warning: {corpus_name} has no 'files' subdirectory, skipping")
                continue

            print(f"Indexing corpus: {corpus_name}...")

            # Collect all .xlsx files
            xlsx_files = list(files_dir.glob("**/*.xlsx"))
            file_paths = [str(f) for f in xlsx_files]

            # Compute statistics
            total_files = len(xlsx_files)
            if total_files == 0:
                print(f"  No .xlsx files found, skipping")
                continue

            # Sample for file size calculation (max 100 files)
            sample_size = min(100, total_files)
            sample_files = random.sample(xlsx_files, sample_size)
            total_size_mb = sum(f.stat().st_size for f in sample_files) / (1024 * 1024)
            avg_file_size_mb = total_size_mb / sample_size

            # Check accessibility on small sample (10 files)
            accessible = 0
            check_sample = random.sample(xlsx_files, min(10, total_files))
            for f in check_sample:
                try:
                    wb = openpyxl.load_workbook(f, read_only=True)
                    wb.close()
                    accessible += 1
                except Exception:
                    pass

            accessible_files = int((accessible / len(check_sample)) * total_files)

            metadata = CorpusMetadata(
                corpus_name=corpus_name,
                source_url=None,  # TODO: Add source URL mapping
                total_files=total_files,
                accessible_files=accessible_files,
                avg_file_size_mb=round(avg_file_size_mb, 2),
                indexed_at=datetime.now().isoformat(),
                file_paths=file_paths
            )

            corpora[corpus_name] = metadata

            print(f"  Total files: {total_files}")
            print(f"  Accessible: ~{accessible_files} ({accessible}/{len(check_sample)} in sample)")
            print(f"  Avg size: {avg_file_size_mb:.2f} MB")

        return corpora

    def validate_corpus(self, corpus_index: Dict[str, CorpusMetadata], sample_size: int = 100):
        """
        Validate corpus accessibility by checking a random sample.

        Args:
            corpus_index: Loaded corpus index
            sample_size: Number of files to check per corpus
        """
        print(f"\nValidating corpus accessibility (sample size: {sample_size})...\n")

        for corpus_name, metadata in corpus_index.items():
            print(f"Corpus: {corpus_name}")

            sample = random.sample(metadata.file_paths, min(sample_size, len(metadata.file_paths)))

            accessible = 0
            errors = defaultdict(int)

            for file_path in sample:
                try:
                    wb = openpyxl.load_workbook(file_path, read_only=True)
                    wb.close()
                    accessible += 1
                except Exception as e:
                    error_type = type(e).__name__
                    errors[error_type] += 1

            accessibility_rate = accessible / len(sample)

            print(f"  Accessibility: {accessible}/{len(sample)} ({accessibility_rate:.1%})")

            if errors:
                print(f"  Errors:")
                for error_type, count in sorted(errors.items(), key=lambda x: -x[1]):
                    print(f"    {error_type}: {count}")

            print()

    def create_w1_sample(self, corpus_index: Dict[str, CorpusMetadata], count: int = 2000) -> List[str]:
        """
        Create a random sample for W1 testing.

        Args:
            corpus_index: Loaded corpus index
            count: Number of files to sample

        Returns:
            List of file paths
        """
        # Combine all file paths
        all_files = []
        for metadata in corpus_index.values():
            all_files.extend(metadata.file_paths)

        if len(all_files) < count:
            print(f"Warning: Only {len(all_files)} files available, sampling all")
            return all_files

        sample = random.sample(all_files, count)
        return sample

    def create_demo_corpus(self, count: int = 100):
        """
        Create a small demo corpus with synthetic workbooks.

        Args:
            count: Number of demo files to create
        """
        demo_dir = self.corpus_root / "demo" / "files"
        demo_dir.mkdir(parents=True, exist_ok=True)

        print(f"Creating demo corpus with {count} synthetic workbooks...")

        for i in range(count):
            file_path = demo_dir / f"demo_{i:04d}.xlsx"

            # Create a simple workbook with formulas
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Sheet1"

            # Add some data and formulas
            ws['A1'] = "Revenue"
            ws['A2'] = "Costs"
            ws['A3'] = "Profit"

            ws['B1'] = 1000 + i * 10
            ws['B2'] = 600 + i * 5
            ws['B3'] = "=B1-B2"

            wb.save(file_path)

            if (i + 1) % 10 == 0:
                print(f"  Created {i + 1}/{count}")

        print(f"Demo corpus created at: {demo_dir}")


def main():
    parser = argparse.ArgumentParser(description="Corpus preparation tool")
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Guide command
    guide_parser = subparsers.add_parser('guide', help='Print corpus download guide')

    # Index command
    index_parser = subparsers.add_parser('index', help='Index corpus directory')
    index_parser.add_argument('corpus_path', type=Path, help='Path to corpus root directory')
    index_parser.add_argument('--output', type=Path, default='corpus_index.json',
                             help='Output index file')

    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate corpus accessibility')
    validate_parser.add_argument('index_file', type=Path, help='Corpus index JSON file')
    validate_parser.add_argument('--sample-size', type=int, default=100,
                                help='Number of files to check per corpus')

    # Sample command
    sample_parser = subparsers.add_parser('sample', help='Create W1 test sample')
    sample_parser.add_argument('index_file', type=Path, help='Corpus index JSON file')
    sample_parser.add_argument('--count', type=int, default=2000,
                              help='Number of files to sample')
    sample_parser.add_argument('--output', type=Path, default='w1_test_sample.json',
                              help='Output sample file')

    # Create demo command
    demo_parser = subparsers.add_parser('create-demo', help='Create demo corpus')
    demo_parser.add_argument('--count', type=int, default=100,
                            help='Number of demo files to create')

    args = parser.parse_args()

    prep = CorpusPreparation()

    if args.command == 'guide':
        prep.print_guide()

    elif args.command == 'index':
        corpora = prep.index_corpus(args.corpus_path)

        # Save index
        index_data = {name: asdict(meta) for name, meta in corpora.items()}
        with open(args.output, 'w') as f:
            json.dump(index_data, f, indent=2)

        print(f"\nIndex saved to: {args.output}")
        print(f"Total corpora: {len(corpora)}")
        print(f"Total files: {sum(m.total_files for m in corpora.values())}")

    elif args.command == 'validate':
        # Load index
        with open(args.index_file, 'r') as f:
            index_data = json.load(f)

        corpus_index = {name: CorpusMetadata(**meta) for name, meta in index_data.items()}
        prep.validate_corpus(corpus_index, args.sample_size)

    elif args.command == 'sample':
        # Load index
        with open(args.index_file, 'r') as f:
            index_data = json.load(f)

        corpus_index = {name: CorpusMetadata(**meta) for name, meta in index_data.items()}
        sample = prep.create_w1_sample(corpus_index, args.count)

        # Save sample
        sample_data = {
            "created_at": datetime.now().isoformat(),
            "sample_size": len(sample),
            "file_paths": sample
        }
        with open(args.output, 'w') as f:
            json.dump(sample_data, f, indent=2)

        print(f"W1 test sample saved to: {args.output}")
        print(f"Sample size: {len(sample)}")

    elif args.command == 'create-demo':
        prep.create_demo_corpus(args.count)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
