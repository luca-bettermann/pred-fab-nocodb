"""Tests for WorkflowsClient.push_study_definition."""
from dataclasses import dataclass, field
from typing import Any

from pred_fab_nocodb.workflows import WorkflowsClient


@dataclass
class _FakeStudy:
    id: int
    code: str


@dataclass
class _StubStudies:
    by_code: dict[str, _FakeStudy] = field(default_factory=dict)
    pushed: list[tuple[int, dict]] = field(default_factory=list)

    def get_by_code(self, code: str) -> _FakeStudy:
        return self.by_code[code]

    def push_schema(self, study_id: int, schema: dict) -> None:
        self.pushed.append((study_id, schema))


@dataclass
class _StubStudyConstants:
    written: list[tuple[int, str, dict]] = field(default_factory=list)

    def write_batch(self, *, study_id: int, study_code: str, constants: dict) -> None:
        self.written.append((study_id, study_code, dict(constants)))


@dataclass
class _FakeClient:
    studies: _StubStudies = field(default_factory=_StubStudies)
    study_constants: _StubStudyConstants = field(default_factory=_StubStudyConstants)


def test_push_study_definition_pushes_schema_and_constants():
    client = _FakeClient()
    client.studies.by_code["ADVEI"] = _FakeStudy(id=42, code="ADVEI")
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    schema = {"schema_id": "ADVEI", "parameters": {}}
    constants = {"W_filament": 0.007, "component_height_mm": 25.0}
    study_id = workflows.push_study_definition(
        study_code="ADVEI", schema=schema, constants=constants,
    )
    assert study_id == 42
    assert client.studies.pushed == [(42, schema)]
    assert client.study_constants.written == [(42, "ADVEI", constants)]


def test_push_study_definition_constants_optional():
    client = _FakeClient()
    client.studies.by_code["ADVEI"] = _FakeStudy(id=42, code="ADVEI")
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    workflows.push_study_definition(study_code="ADVEI", schema={"x": 1})
    assert client.studies.pushed == [(42, {"x": 1})]
    assert client.study_constants.written == []


def test_push_study_definition_empty_constants_skips_write():
    client = _FakeClient()
    client.studies.by_code["ADVEI"] = _FakeStudy(id=42, code="ADVEI")
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    workflows.push_study_definition(
        study_code="ADVEI", schema={"x": 1}, constants={},
    )
    # Schema pushed; empty constants → no write_batch call
    assert client.studies.pushed == [(42, {"x": 1})]
    assert client.study_constants.written == []
