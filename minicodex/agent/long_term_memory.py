"""Persistent cross-task memory for MiniCodex."""

from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    datetime,
    timezone,
)
from hashlib import sha256
from pathlib import Path
import json
import re
import uuid


# =============================================================
# Long-Term Memory Record
# =============================================================


@dataclass(frozen=True)
class LongTermMemoryRecord:
    """
    One compact historical task experience.

    Long-term memory is historical context.

    It is NOT source of truth for the current repository.
    """

    memory_id: str

    created_at: str

    repository_key: str

    task_prompt: str

    outcome: str

    summary: str

    touched_files: tuple[
        str,
        ...,
    ] = ()

    tags: tuple[
        str,
        ...,
    ] = ()

    fingerprint: str = ""

    def to_dict(
        self,
    ) -> dict:

        return asdict(
            self
        )

    @classmethod
    def from_dict(
        cls,
        data: dict,
    ) -> "LongTermMemoryRecord":

        return cls(
            memory_id=str(
                data.get(
                    "memory_id",
                    "",
                )
            ),
            created_at=str(
                data.get(
                    "created_at",
                    "",
                )
            ),
            repository_key=str(
                data.get(
                    "repository_key",
                    "",
                )
            ),
            task_prompt=str(
                data.get(
                    "task_prompt",
                    "",
                )
            ),
            outcome=str(
                data.get(
                    "outcome",
                    "",
                )
            ),
            summary=str(
                data.get(
                    "summary",
                    "",
                )
            ),
            touched_files=tuple(
                str(
                    item
                )
                for item
                in (
                    data.get(
                        "touched_files",
                        [],
                    )
                    or []
                )
            ),
            tags=tuple(
                str(
                    item
                )
                for item
                in (
                    data.get(
                        "tags",
                        [],
                    )
                    or []
                )
            ),
            fingerprint=str(
                data.get(
                    "fingerprint",
                    "",
                )
            ),
        )


# =============================================================
# Retrieval Result
# =============================================================


@dataclass(frozen=True)
class RetrievedMemory:

    record: LongTermMemoryRecord

    score: float


# =============================================================
# Persistent Store
# =============================================================


class LongTermMemoryStore:
    """
    Deterministic local persistent memory store.

    Storage format:

        JSON

    Retrieval:

        lexical overlap
        +
        file-name overlap
        +
        small successful-task bonus

    This stage deliberately does NOT require:

        vector DB
        embeddings
        external services
        LLM-as-memory-manager

    Those can be added later without changing the public
    memory interface.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        path,
        repository_key: str | None = None,
        max_records: int = 200,
        max_prompt_chars: int = 600,
        max_summary_chars: int = 1600,
    ):

        self.path = (
            Path(
                path
            )
            .resolve()
        )

        self.repository_key = (
            str(
                repository_key
            )
            .strip()
            if repository_key
            else (
                self.path
                .parent
                .parent
                .parent
                .name
            )
        )

        self.max_records = max(
            1,
            int(
                max_records
            ),
        )

        self.max_prompt_chars = max(
            50,
            int(
                max_prompt_chars
            ),
        )

        self.max_summary_chars = max(
            100,
            int(
                max_summary_chars
            ),
        )

        self.records: list[
            LongTermMemoryRecord
        ] = []

        self.load()

    # =========================================================
    # Load
    # =========================================================

    def load(
        self,
    ) -> None:

        self.records = []

        if not (
            self.path.exists()
        ):

            return

        if not (
            self.path.is_file()
        ):

            return

        try:

            raw = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ):

            return

        if not isinstance(
            raw,
            dict,
        ):

            return

        raw_records = (
            raw.get(
                "records",
                [],
            )
        )

        if not isinstance(
            raw_records,
            list,
        ):

            return

        loaded = []

        for item in (
            raw_records
        ):

            if not isinstance(
                item,
                dict,
            ):

                continue

            try:

                record = (
                    LongTermMemoryRecord
                    .from_dict(
                        item
                    )
                )

            except Exception:

                continue

            if not (
                record.memory_id
                and record.repository_key
            ):

                continue

            loaded.append(
                record
            )

        self.records = (
            loaded[
                -self.max_records:
            ]
        )

    # =========================================================
    # Create Record
    # =========================================================

    def create_record(
        self,
        *,
        task_prompt: str,
        outcome: str,
        summary: str,
        touched_files=(),
        tags=(),
    ) -> LongTermMemoryRecord:

        normalized_prompt = (
            self._truncate(
                task_prompt,
                self.max_prompt_chars,
            )
        )

        normalized_summary = (
            self._truncate(
                summary,
                self.max_summary_chars,
            )
        )

        normalized_files = tuple(
            sorted(
                {
                    str(
                        item
                    ).strip()
                    for item
                    in touched_files
                    if str(
                        item
                    ).strip()
                }
            )
        )

        normalized_tags = tuple(
            sorted(
                {
                    str(
                        item
                    ).strip()
                    .lower()
                    for item
                    in tags
                    if str(
                        item
                    ).strip()
                }
            )
        )

        fingerprint = (
            self._fingerprint(
                normalized_prompt
            )
        )

        return (
            LongTermMemoryRecord(
                memory_id=(
                    uuid.uuid4()
                    .hex
                ),
                created_at=(
                    datetime.now(
                        timezone.utc
                    )
                    .isoformat()
                ),
                repository_key=(
                    self.repository_key
                ),
                task_prompt=(
                    normalized_prompt
                ),
                outcome=(
                    str(
                        outcome
                    )
                    .strip()
                    .lower()
                    or "unknown"
                ),
                summary=(
                    normalized_summary
                ),
                touched_files=(
                    normalized_files
                ),
                tags=(
                    normalized_tags
                ),
                fingerprint=(
                    fingerprint
                ),
            )
        )

    # =========================================================
    # Remember
    # =========================================================

    def remember(
        self,
        record: LongTermMemoryRecord,
    ) -> None:
        """
        Persist one task experience.

        Re-running substantially the same task replaces the old
        memory instead of accumulating duplicate memories.
        """

        if (
            record.repository_key
            != self.repository_key
        ):

            return

        records = [
            existing
            for existing
            in self.records
            if (
                existing.fingerprint
                != record.fingerprint
            )
        ]

        records.append(
            record
        )

        self.records = (
            records[
                -self.max_records:
            ]
        )

        self.save()

    # =========================================================
    # Retrieve
    # =========================================================

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[
        RetrievedMemory
    ]:

        query_tokens = (
            self._tokenize(
                query
            )
        )

        if not (
            query_tokens
        ):

            return []

        candidates = []

        for index, record in enumerate(
            self.records
        ):

            if (
                record.repository_key
                != self.repository_key
            ):

                continue

            score = (
                self._score(
                    query_tokens=(
                        query_tokens
                    ),
                    record=(
                        record
                    ),
                    recency_index=(
                        index
                    ),
                )
            )

            if (
                score
                <= 0
            ):

                continue

            candidates.append(
                RetrievedMemory(
                    record=(
                        record
                    ),
                    score=(
                        score
                    ),
                )
            )

        candidates.sort(
            key=lambda item: (
                item.score,
                item.record.created_at,
            ),
            reverse=True,
        )

        return (
            candidates[
                :max(
                    1,
                    int(
                        limit
                    ),
                )
            ]
        )

    # =========================================================
    # Render Retrieval
    # =========================================================

    def render_retrieved(
        self,
        retrieved: list[
            RetrievedMemory
        ],
    ) -> str:

        if not (
            retrieved
        ):

            return (
                "No relevant historical "
                "task memory was retrieved."
            )

        lines = [
            (
                "Relevant long-term memory "
                "(historical only; verify current "
                "repository state with tools):"
            )
        ]

        for item in (
            retrieved
        ):

            record = (
                item.record
            )

            lines.append(
                (
                    f"- [{record.outcome}] "
                    f"Previous task: "
                    f"{record.task_prompt}"
                )
            )

            if (
                record.summary
            ):

                lines.append(
                    (
                        "  Experience: "
                        f"{record.summary}"
                    )
                )

            if (
                record.touched_files
            ):

                lines.append(
                    (
                        "  Previously touched: "
                        + ", ".join(
                            record.touched_files
                        )
                    )
                )

        return "\n".join(
            lines
        )

    # =========================================================
    # Save
    # =========================================================

    def save(
        self,
    ) -> None:
        """
        Atomic local persistence.

        Write temporary file first, then replace.
        """

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "schema_version": (
                self.SCHEMA_VERSION
            ),
            "repository_key": (
                self.repository_key
            ),
            "records": [
                record.to_dict()
                for record
                in self.records
            ],
        }

        temporary = (
            self.path
            .with_suffix(
                self.path.suffix
                + ".tmp"
            )
        )

        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temporary.replace(
            self.path
        )

    # =========================================================
    # Score
    # =========================================================

    def _score(
        self,
        *,
        query_tokens: set[str],
        record: LongTermMemoryRecord,
        recency_index: int,
    ) -> float:

        searchable = " ".join(
            [
                record.task_prompt,
                record.summary,
                " ".join(
                    record.touched_files
                ),
                " ".join(
                    record.tags
                ),
            ]
        )

        memory_tokens = (
            self._tokenize(
                searchable
            )
        )

        if not (
            memory_tokens
        ):

            return 0.0

        overlap = (
            query_tokens
            & memory_tokens
        )

        if not (
            overlap
        ):

            return 0.0

        lexical_score = (
            len(
                overlap
            )
            / max(
                1,
                len(
                    query_tokens
                ),
            )
        )

        filename_bonus = 0.0

        lowered_query = (
            " ".join(
                query_tokens
            )
        )

        for path in (
            record.touched_files
        ):

            name = (
                Path(
                    path
                )
                .name
                .lower()
            )

            if (
                name
                and name
                in lowered_query
            ):

                filename_bonus = (
                    0.35
                )

                break

        outcome_bonus = (
            0.08
            if (
                record.outcome
                == "success"
            )
            else 0.0
        )

        recency_bonus = (
            min(
                0.07,
                (
                    recency_index
                    + 1
                )
                / max(
                    1,
                    len(
                        self.records
                    ),
                )
                * 0.07,
            )
        )

        return (
            lexical_score
            + filename_bonus
            + outcome_bonus
            + recency_bonus
        )

    # =========================================================
    # Tokenize
    # =========================================================

    @staticmethod
    def _tokenize(
        text: str,
    ) -> set[str]:

        normalized = (
            str(
                text
            )
            .lower()
        )

        tokens = set(
            re.findall(
                r"[a-z0-9_./-]{2,}",
                normalized,
            )
        )

        chinese_sequences = re.findall(
            r"[\u4e00-\u9fff]+",
            normalized,
        )

        for sequence in (
            chinese_sequences
        ):

            if (
                len(
                    sequence
                )
                == 1
            ):

                tokens.add(
                    sequence
                )

                continue

            for index in range(
                len(
                    sequence
                )
                - 1
            ):

                tokens.add(
                    sequence[
                        index:
                        index + 2
                    ]
                )

        return tokens

    # =========================================================
    # Fingerprint
    # =========================================================

    def _fingerprint(
        self,
        task_prompt: str,
    ) -> str:

        normalized = " ".join(
            str(
                task_prompt
            )
            .lower()
            .split()
        )

        raw = (
            f"{self.repository_key}\n"
            f"{normalized}"
        )

        return (
            sha256(
                raw.encode(
                    "utf-8"
                )
            )
            .hexdigest()
        )

    # =========================================================
    # Truncate
    # =========================================================

    @staticmethod
    def _truncate(
        value,
        limit: int,
    ) -> str:

        text = (
            str(
                value
            )
            .strip()
        )

        if (
            len(
                text
            )
            <= limit
        ):

            return text

        return (
            text[
                :limit
            ]
            .rstrip()
            + "…"
        )