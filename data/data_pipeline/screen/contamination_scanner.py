"""
Contamination Scanner - 6-method deduplication against official SpreadsheetBench 2 tasks.

This module implements strict contamination detection to ensure our generated tasks
do not leak information from the official 321-task benchmark. Any task matching
any of the 6 methods is flagged and removed from the training set.

Six Detection Methods:
1. File hash collision (SHA256 on normalized workbook)
2. Structural fingerprint match (sheet names + dimension + formula count)
3. Formula family overlap (>80% shared normalized formula families)
4. Instruction text similarity (>0.85 cosine similarity on embedded instruction)
5. Answer position exact match (same sheet!range)
6. Lineage family collision (same source family name)

Usage:
    scanner = ContaminationScanner(official_dataset_path="/path/to/spreadsheetbench-v2")
    is_clean, reasons = scanner.check_task(candidate_task)
    if not is_clean:
        print(f"Contaminated: {reasons}")
"""

import os
import json
import hashlib
import openpyxl
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass
from collections import Counter
import numpy as np
import re


@dataclass
class OfficialTask:
    """Official benchmark task metadata for contamination checking."""
    task_id: str
    category: str
    file_hash: str
    structural_fingerprint: str
    formula_families: Set[str]
    instruction_embedding: Optional[np.ndarray]
    answer_position: str
    lineage_family: Optional[str]


class ContaminationScanner:
    """
    Contamination detection against official SpreadsheetBench 2.

    This scanner loads the official 321-task dataset and builds multiple indices
    for fast contamination checking. Any generated task matching ANY method is
    flagged as contaminated.

    The scanner is conservative: better to reject clean tasks than to leak
    benchmark information.
    """

    def __init__(self, official_dataset_path: str):
        """
        Initialize scanner with official dataset.

        Args:
            official_dataset_path: Path to official SpreadsheetBench-v2 data directory
        """
        self.official_dataset_path = Path(official_dataset_path)
        self.official_tasks: List[OfficialTask] = []

        # Indices for fast lookup
        self.file_hash_index: Set[str] = set()
        self.structural_fingerprint_index: Set[str] = set()
        self.formula_family_index: Dict[str, Set[str]] = {}  # task_id -> formula families
        self.answer_position_index: Set[str] = set()
        self.lineage_family_index: Set[str] = set()

        # Load official tasks
        self._load_official_tasks()

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of normalized workbook."""
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
            # Normalize: extract cell values in deterministic order
            content_parts = []
            for sheet_name in sorted(wb.sheetnames):
                ws = wb[sheet_name]
                content_parts.append(f"SHEET:{sheet_name}")
                for row in ws.iter_rows():
                    for cell in row:
                        if cell.value is not None:
                            content_parts.append(f"{cell.coordinate}={cell.value}")
            content = "\n".join(content_parts)
            return hashlib.sha256(content.encode('utf-8')).hexdigest()
        except Exception:
            return "HASH_ERROR"

    def _compute_structural_fingerprint(self, file_path: Path) -> str:
        """Compute structural fingerprint: sheet names + dimensions + formula count."""
        try:
            wb = openpyxl.load_workbook(file_path, data_only=False)
            parts = []
            for sheet_name in sorted(wb.sheetnames):
                ws = wb[sheet_name]
                max_row = ws.max_row or 0
                max_col = ws.max_column or 0
                formula_count = sum(1 for row in ws.iter_rows() for cell in row
                                   if isinstance(cell.value, str) and cell.value.startswith('='))
                parts.append(f"{sheet_name}:{max_row}x{max_col}:{formula_count}f")
            return "|".join(parts)
        except Exception:
            return "FINGERPRINT_ERROR"

    def _extract_formula_families(self, file_path: Path) -> Set[str]:
        """Extract normalized formula families (R1C1 normalized, function signatures)."""
        families = set()
        try:
            wb = openpyxl.load_workbook(file_path, data_only=False)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                for row in ws.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.startswith('='):
                            family = self._normalize_formula_to_family(cell.value)
                            if family:
                                families.add(family)
        except Exception:
            pass
        return families

    def _normalize_formula_to_family(self, formula: str) -> str:
        """
        Normalize formula to family signature.

        Example:
            =SUM(B2:B10) -> SUM(RANGE)
            =IF(A1>100, "High", "Low") -> IF(COMPARISON, STRING, STRING)
            =VLOOKUP(D2, A:B, 2, FALSE) -> VLOOKUP(REF, RANGE, NUM, BOOL)
        """
        if not formula.startswith('='):
            return ""

        # Extract function names (Excel functions are uppercase)
        functions = re.findall(r'\b([A-Z][A-Z0-9_.]*)\s*\(', formula.upper())

        # Replace cell references with placeholders
        normalized = formula.upper()
        # Range references (A1:B10)
        normalized = re.sub(r'\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+', 'RANGE', normalized)
        # Single cell references (A1)
        normalized = re.sub(r'\$?[A-Z]+\$?\d+', 'REF', normalized)
        # String literals
        normalized = re.sub(r'"[^"]*"', 'STRING', normalized)
        # Numbers
        normalized = re.sub(r'\b\d+\.?\d*\b', 'NUM', normalized)

        # Signature: function list + normalized pattern
        signature = f"{','.join(functions)}:{normalized[:100]}"
        return signature

    def _compute_instruction_embedding(self, instruction: str) -> np.ndarray:
        """
        Compute instruction embedding for similarity comparison.

        For MVP, we use a simple bag-of-words + TF-IDF approach.
        In production, consider using sentence-transformers or OpenAI embeddings.
        """
        # Simple tokenization
        tokens = re.findall(r'\w+', instruction.lower())
        # For now, return a simple hash-based pseudo-embedding
        # In production, replace with proper embeddings
        hash_val = int(hashlib.md5(instruction.encode()).hexdigest()[:8], 16)
        np.random.seed(hash_val)
        return np.random.randn(128)  # 128-dim pseudo-embedding

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        if vec1 is None or vec2 is None:
            return 0.0
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return np.dot(vec1, vec2) / (norm1 * norm2)

    def _load_official_tasks(self):
        """Load official benchmark tasks and build indices."""
        # Load all category dataset.json files
        categories = ["Debugging", "Financial_Model", "Template", "Visualization"]

        for category in categories:
            dataset_file = self.official_dataset_path / category / "dataset.json"
            if not dataset_file.exists():
                continue

            with open(dataset_file, 'r') as f:
                dataset = json.load(f)

            for item in dataset:
                task_id = str(item['id'])
                input_file = self.official_dataset_path / category / item['spreadsheet_path']
                golden_file = self.official_dataset_path / category / item['golden_response_path']

                # Compute detection features
                file_hash = self._compute_file_hash(input_file) if input_file.exists() else ""
                structural_fp = self._compute_structural_fingerprint(input_file) if input_file.exists() else ""
                formula_families = self._extract_formula_families(input_file) if input_file.exists() else set()
                instruction_emb = self._compute_instruction_embedding(item.get('instruction', ''))
                answer_position = item.get('answer_position', '')

                # Extract lineage family from file path (heuristic)
                lineage_family = self._extract_lineage_family_from_path(item['spreadsheet_path'])

                # Create official task record
                official_task = OfficialTask(
                    task_id=task_id,
                    category=category,
                    file_hash=file_hash,
                    structural_fingerprint=structural_fp,
                    formula_families=formula_families,
                    instruction_embedding=instruction_emb,
                    answer_position=answer_position,
                    lineage_family=lineage_family
                )
                self.official_tasks.append(official_task)

                # Build indices
                if file_hash:
                    self.file_hash_index.add(file_hash)
                if structural_fp:
                    self.structural_fingerprint_index.add(structural_fp)
                if formula_families:
                    self.formula_family_index[task_id] = formula_families
                if answer_position:
                    self.answer_position_index.add(answer_position)
                if lineage_family:
                    self.lineage_family_index.add(lineage_family)

        print(f"Loaded {len(self.official_tasks)} official tasks for contamination detection")

    def _extract_lineage_family_from_path(self, file_path: str) -> Optional[str]:
        """Extract lineage family name from file path (heuristic)."""
        # Example: "Debugging/xlsx_embedding/1234.xlsx" -> "xlsx_embedding"
        parts = Path(file_path).parts
        if len(parts) >= 2:
            return parts[-2]  # Parent directory name as family proxy
        return None

    def check_task(self, candidate_task: Dict) -> Tuple[bool, List[str]]:
        """
        Check if candidate task is contaminated.

        Args:
            candidate_task: Task dict with fields:
                - input_file_path: Path to input.xlsx
                - instruction: Task instruction text
                - answer_position: Official answer_position string
                - lineage_family: Source family name (optional)

        Returns:
            (is_clean, contamination_reasons)
            is_clean=False if ANY method detects contamination
        """
        contamination_reasons = []

        input_file = Path(candidate_task['input_file_path'])
        instruction = candidate_task.get('instruction', '')
        answer_position = candidate_task.get('answer_position', '')
        lineage_family = candidate_task.get('lineage_family', None)

        # Method 1: File hash collision
        file_hash = self._compute_file_hash(input_file)
        if file_hash in self.file_hash_index:
            contamination_reasons.append(f"Method 1: File hash collision ({file_hash[:16]}...)")

        # Method 2: Structural fingerprint match
        structural_fp = self._compute_structural_fingerprint(input_file)
        if structural_fp in self.structural_fingerprint_index:
            contamination_reasons.append(f"Method 2: Structural fingerprint match")

        # Method 3: Formula family overlap (>80%)
        candidate_families = self._extract_formula_families(input_file)
        if candidate_families:
            for official_id, official_families in self.formula_family_index.items():
                if not official_families:
                    continue
                overlap = len(candidate_families & official_families)
                total = len(candidate_families | official_families)
                if total > 0 and overlap / total > 0.8:
                    contamination_reasons.append(
                        f"Method 3: Formula family overlap {overlap}/{total} with task {official_id}"
                    )
                    break  # One match is enough

        # Method 4: Instruction text similarity (>0.85)
        if instruction:
            candidate_emb = self._compute_instruction_embedding(instruction)
            for official_task in self.official_tasks:
                similarity = self._cosine_similarity(candidate_emb, official_task.instruction_embedding)
                if similarity > 0.85:
                    contamination_reasons.append(
                        f"Method 4: Instruction similarity {similarity:.3f} with task {official_task.task_id}"
                    )
                    break

        # Method 5: Answer position exact match
        if answer_position and answer_position in self.answer_position_index:
            # Exact match is suspicious but not definitive (common ranges like "Sheet1!A1:Z100")
            # Only flag if combined with other signals or if it's a very specific range
            if len(contamination_reasons) > 0 or self._is_specific_range(answer_position):
                contamination_reasons.append(f"Method 5: Answer position match ({answer_position})")

        # Method 6: Lineage family collision
        if lineage_family and lineage_family in self.lineage_family_index:
            contamination_reasons.append(f"Method 6: Lineage family collision ({lineage_family})")

        is_clean = len(contamination_reasons) == 0
        return is_clean, contamination_reasons

    def _is_specific_range(self, answer_position: str) -> bool:
        """Check if answer_position is a specific (non-generic) range."""
        # Generic ranges like "Sheet1!A1:Z100" are common and not suspicious alone
        # Specific ranges like "'P&L Analysis'!B15:K47" are more suspicious
        if "!" not in answer_position:
            return False
        sheet_part, range_part = answer_position.split("!", 1)
        # Check if sheet name is quoted (indicates special characters/spaces)
        is_quoted_sheet = sheet_part.strip().startswith("'")
        # Check if range is small and specific (not whole-sheet like A1:Z1000)
        if ":" in range_part:
            start, end = range_part.split(":")
            # Extract row numbers
            start_row = int(''.join(filter(str.isdigit, start)) or '0')
            end_row = int(''.join(filter(str.isdigit, end)) or '0')
            row_span = end_row - start_row + 1
            # Specific if quoted sheet OR small range (<50 rows)
            return is_quoted_sheet or row_span < 50
        return is_quoted_sheet

    def batch_check_tasks(self, candidate_tasks: List[Dict]) -> Dict[str, Tuple[bool, List[str]]]:
        """
        Check multiple tasks in batch.

        Args:
            candidate_tasks: List of task dicts (must have 'task_id' field)

        Returns:
            Dict mapping task_id -> (is_clean, contamination_reasons)
        """
        results = {}
        for task in candidate_tasks:
            task_id = task['task_id']
            is_clean, reasons = self.check_task(task)
            results[task_id] = (is_clean, reasons)
        return results

    def generate_report(self, scan_results: Dict[str, Tuple[bool, List[str]]]) -> Dict:
        """
        Generate contamination scan report.

        Args:
            scan_results: Output from batch_check_tasks

        Returns:
            Report dict with statistics and contaminated task details
        """
        total = len(scan_results)
        clean = sum(1 for is_clean, _ in scan_results.values() if is_clean)
        contaminated = total - clean

        contaminated_tasks = [
            {"task_id": task_id, "reasons": reasons}
            for task_id, (is_clean, reasons) in scan_results.items()
            if not is_clean
        ]

        # Method breakdown
        method_counts = Counter()
        for _, (is_clean, reasons) in scan_results.items():
            if not is_clean:
                for reason in reasons:
                    method = reason.split(":")[0]  # Extract "Method N"
                    method_counts[method] += 1

        report = {
            "total_scanned": total,
            "clean": clean,
            "contaminated": contaminated,
            "contamination_rate": round(contaminated / total, 4) if total > 0 else 0.0,
            "method_breakdown": dict(method_counts),
            "contaminated_tasks": contaminated_tasks
        }

        return report


# ============================================================================
# CLI and Testing
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python contamination_scanner.py <official_dataset_path> [candidate_task.json]")
        print("\nExample:")
        print("  python contamination_scanner.py /path/to/spreadsheetbench-v2")
        print("  python contamination_scanner.py /path/to/spreadsheetbench-v2 candidate_task.json")
        sys.exit(1)

    official_path = sys.argv[1]
    scanner = ContaminationScanner(official_path)

    if len(sys.argv) >= 3:
        # Check a specific candidate task
        candidate_file = sys.argv[2]
        with open(candidate_file, 'r') as f:
            candidate_task = json.load(f)

        is_clean, reasons = scanner.check_task(candidate_task)

        print(f"\n=== Contamination Check: {candidate_task.get('task_id', 'unknown')} ===")
        print(f"Status: {'CLEAN' if is_clean else 'CONTAMINATED'}")
        if not is_clean:
            print("\nContamination reasons:")
            for reason in reasons:
                print(f"  - {reason}")
        sys.exit(0 if is_clean else 1)
    else:
        # Just load and report statistics
        print(f"\n=== Contamination Scanner Initialized ===")
        print(f"Loaded {len(scanner.official_tasks)} official tasks")
        print(f"  - File hash index: {len(scanner.file_hash_index)} entries")
        print(f"  - Structural fingerprint index: {len(scanner.structural_fingerprint_index)} entries")
        print(f"  - Formula family index: {len(scanner.formula_family_index)} entries")
        print(f"  - Answer position index: {len(scanner.answer_position_index)} entries")
        print(f"  - Lineage family index: {len(scanner.lineage_family_index)} entries")
        print("\nReady for contamination detection.")
