"""
S0 资产入库 - 来源登记模块

实现lineage追踪，确保每个文件都有明确的来源信息。
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
import hashlib


@dataclass
class Lineage:
    """来源血缘信息"""
    lineage_id: str  # 唯一标识，格式：family_NNNN
    family_name: str  # 家族名称（用于split切分）
    source_type: str  # 来源类型：financial_report, template, teaching_material, etc.

    # 可选字段
    source_url: Optional[str] = None
    company: Optional[str] = None
    period: Optional[str] = None  # 如：2023Q4
    industry: Optional[str] = None
    template_author: Optional[str] = None
    license: Optional[str] = None

    # 构建信息
    builder: Optional[str] = None  # 构建者ID
    created_at: Optional[str] = None
    notes: Optional[str] = None

    # 元数据
    original_filename: Optional[str] = None
    file_hash: Optional[str] = None
    file_size_bytes: Optional[int] = None


class LineageRegistry:
    """来源登记表"""

    def __init__(self, registry_path: Path):
        """
        Args:
            registry_path: 登记表JSON文件路径
        """
        self.registry_path = registry_path
        self.registry: Dict[str, Lineage] = {}

        # 加载已有登记表
        if registry_path.exists():
            self.load()

    def load(self):
        """加载登记表"""
        with open(self.registry_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.registry = {
            lineage_id: Lineage(**info)
            for lineage_id, info in data.items()
        }

    def save(self):
        """保存登记表"""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            lineage_id: asdict(lineage)
            for lineage_id, lineage in self.registry.items()
        }

        with open(self.registry_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def register(
        self,
        file_path: Path,
        family_name: str,
        source_type: str,
        **kwargs
    ) -> str:
        """
        登记一个新文件

        Args:
            file_path: 文件路径
            family_name: 家族名称
            source_type: 来源类型
            **kwargs: 其他可选字段

        Returns:
            生成的lineage_id
        """
        # 生成lineage_id
        lineage_id = self._generate_lineage_id(family_name)

        # 计算文件哈希
        file_hash = self._compute_file_hash(file_path)

        # 创建Lineage对象
        lineage = Lineage(
            lineage_id=lineage_id,
            family_name=family_name,
            source_type=source_type,
            original_filename=file_path.name,
            file_hash=file_hash,
            file_size_bytes=file_path.stat().st_size,
            created_at=datetime.now().isoformat(),
            **kwargs
        )

        # 检查是否已存在
        if lineage_id in self.registry:
            raise ValueError(f"Lineage ID {lineage_id} 已存在")

        self.registry[lineage_id] = lineage
        self.save()  # 立即保存到磁盘
        return lineage_id

    def get(self, lineage_id: str) -> Optional[Lineage]:
        """获取lineage信息"""
        return self.registry.get(lineage_id)

    def get_by_family(self, family_name: str) -> List[Lineage]:
        """获取同一家族的所有lineage"""
        return [
            lineage for lineage in self.registry.values()
            if lineage.family_name == family_name
        ]

    def exists(self, lineage_id: str) -> bool:
        """检查lineage_id是否存在"""
        return lineage_id in self.registry

    def get_all_families(self) -> List[str]:
        """获取所有家族名称"""
        return list(set(
            lineage.family_name
            for lineage in self.registry.values()
        ))

    def _generate_lineage_id(self, family_name: str) -> str:
        """
        生成lineage_id

        格式：family_NNNN，其中NNNN是该家族的序号
        """
        # 获取该家族已有的最大序号
        existing = self.get_by_family(family_name)
        if not existing:
            seq = 1
        else:
            # 提取序号
            seqs = []
            for lineage in existing:
                # The lineage_id format is "{family_name}_{seq:04d}"
                # So we need to strip the family_name prefix to get the sequence
                if lineage.lineage_id.startswith(family_name + '_'):
                    seq_str = lineage.lineage_id[len(family_name) + 1:]
                    if seq_str.isdigit():
                        seqs.append(int(seq_str))

            seq = max(seqs) + 1 if seqs else 1

        return f"{family_name}_{seq:04d}"

    def _compute_file_hash(self, file_path: Path) -> str:
        """计算文件SHA256哈希"""
        sha256 = hashlib.sha256()

        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)

        return sha256.hexdigest()

    def export_manifest(self, output_path: Path):
        """导出清单（用于审核和文档）"""
        manifest = []

        for lineage in self.registry.values():
            manifest.append({
                "lineage_id": lineage.lineage_id,
                "family": lineage.family_name,
                "type": lineage.source_type,
                "company": lineage.company,
                "period": lineage.period,
                "source": lineage.source_url,
                "license": lineage.license,
                "created": lineage.created_at
            })

        # 按family和lineage_id排序
        manifest.sort(key=lambda x: (x["family"], x["lineage_id"]))

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)


class LineageValidator:
    """Lineage验证器"""

    REQUIRED_FIELDS = ["lineage_id", "family_name", "source_type"]

    VALID_SOURCE_TYPES = [
        "financial_report",
        "exchange_filing",
        "government_data",
        "international_org",
        "teaching_template",
        "licensed_internal",
        "expert_reconstructed"
    ]

    @classmethod
    def validate(cls, lineage: Lineage) -> List[str]:
        """
        验证lineage是否完整

        Returns:
            错误列表（空列表表示验证通过）
        """
        errors = []

        # 检查必填字段
        for field in cls.REQUIRED_FIELDS:
            if not getattr(lineage, field):
                errors.append(f"缺少必填字段: {field}")

        # 检查source_type是否有效
        if lineage.source_type not in cls.VALID_SOURCE_TYPES:
            errors.append(
                f"无效的source_type: {lineage.source_type}，"
                f"有效值: {cls.VALID_SOURCE_TYPES}"
            )

        # 检查lineage_id格式
        if lineage.lineage_id:
            parts = lineage.lineage_id.split('_')
            if len(parts) != 2 or not parts[1].isdigit():
                errors.append(
                    f"lineage_id格式错误: {lineage.lineage_id}，"
                    "应为 family_NNNN"
                )

        # 对于某些类型，检查额外字段
        if lineage.source_type in ["financial_report", "exchange_filing"]:
            if not lineage.company:
                errors.append(f"{lineage.source_type}类型需要company字段")
            if not lineage.period:
                errors.append(f"{lineage.source_type}类型需要period字段")

        # 检查许可信息
        if not lineage.license:
            errors.append("建议提供license信息")

        return errors


def batch_register(
    file_paths: List[Path],
    registry: LineageRegistry,
    metadata_func: callable
) -> Dict[Path, str]:
    """
    批量登记文件

    Args:
        file_paths: 文件路径列表
        registry: LineageRegistry实例
        metadata_func: 函数(file_path) -> dict，返回元数据

    Returns:
        文件路径到lineage_id的映射
    """
    results = {}

    for file_path in file_paths:
        try:
            # 获取元数据
            metadata = metadata_func(file_path)

            # 验证必填字段
            if "family_name" not in metadata or "source_type" not in metadata:
                print(f"跳过 {file_path.name}: 缺少family_name或source_type")
                continue

            # 登记
            lineage_id = registry.register(file_path, **metadata)
            results[file_path] = lineage_id

            print(f"✓ {file_path.name} -> {lineage_id}")

        except Exception as e:
            print(f"✗ {file_path.name}: {e}")

    # 保存
    registry.save()
    print(f"\n已登记 {len(results)} 个文件")

    return results


if __name__ == "__main__":
    # 测试示例
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # 创建注册表
        registry = LineageRegistry(tmpdir / "lineage_registry.json")

        # 模拟登记
        dummy_file = tmpdir / "test.xlsx"
        dummy_file.write_bytes(b"dummy content")

        lineage_id = registry.register(
            file_path=dummy_file,
            family_name="test_family",
            source_type="teaching_template",
            company="Example Corp",
            period="2023Q4",
            license="CC BY-SA 4.0",
            builder="expert_001"
        )

        print(f"生成的lineage_id: {lineage_id}")

        # 保存
        registry.save()

        # 重新加载
        registry2 = LineageRegistry(tmpdir / "lineage_registry.json")
        lineage = registry2.get(lineage_id)

        print(f"\n重新加载的lineage:")
        print(json.dumps(asdict(lineage), indent=2, ensure_ascii=False))

        # 验证
        errors = LineageValidator.validate(lineage)
        if errors:
            print(f"\n验证错误: {errors}")
        else:
            print("\n✓ 验证通过")
