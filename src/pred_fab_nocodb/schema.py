"""Schema constants — table and column names for the NocoDB layout.

Single source of truth for cross-module string literals. Every other module
imports from here; never duplicates a literal.
"""
from __future__ import annotations

from enum import StrEnum


class Tables:
    """NocoDB table names."""

    STUDIES = "studies"
    EXPERIMENTS = "experiments"
    DATASETS = "datasets"
    DIM_POSITIONS = "dim_positions"
    SET_STUDY_CONSTANTS = "set_study_constants"
    SET_EXP_PARAMS = "set_exp_params"
    SET_EXP_FEATURES = "set_exp_features"
    SET_EXP_ATTRIBUTES = "set_exp_attributes"


class StudyColumns:
    """Columns on the `studies` table."""

    ID = "Id"
    CODE = "code"
    DESCRIPTION = "description"
    STARTED_AT = "started_at"
    ENDED_AT = "ended_at"
    SCHEMA = "schema"
    DATASETS = "datasets"  # LinkToAnotherRecord -> datasets (nullable)


class ExperimentColumns:
    """Columns on the `experiments` table."""

    ID = "Id"
    CODE = "code"
    STUDIES = "studies"  # LinkToAnotherRecord -> studies
    DATASET = "dataset"  # LinkToAnotherRecord -> datasets (nullable)
    STATUS = "status"
    STARTED_AT = "started_at"
    ENDED_AT = "ended_at"
    NOTES = "notes"


class DatasetColumns:
    """Columns on the `datasets` table."""

    ID = "Id"
    CODE = "code"
    STUDY = "study"  # LinkToAnotherRecord -> studies
    NAME = "name"
    STRATEGY = "strategy"  # how experiments were generated
    PURPOSE = "purpose"  # how they're used
    DESCRIPTION = "description"


class DimPositionColumns:
    """Columns on the `dim_positions` table."""

    ID = "Id"
    CODE = "code"
    DOMAIN = "domain"
    DEPTH = "depth"
    AXES = "axes"
    CONTAINED_IN = "contained_in"  # self-link to ancestor dim_positions


class StudyConstantColumns:
    """Columns on the `set_study_constants` table."""

    ID = "Id"
    CODE = "code"
    STUDY = "study"  # LinkToAnotherRecord -> studies
    PARAM = "param"  # the constant's identifying code
    VALUE = "value"


class ParamColumns:
    """Columns on the `set_exp_params` table."""

    ID = "Id"
    CODE = "code"
    EXPERIMENT = "experiment"  # LinkToAnotherRecord -> experiments
    PARAM = "param"  # the parameter's identifying code
    DIM = "dim"  # LinkToAnotherRecord -> dim_positions (nullable)
    VALUE = "value"


class FeatureColumns:
    """Columns on the `set_exp_features` table."""

    ID = "Id"
    CODE = "code"
    EXPERIMENT = "experiment"
    FEATURE = "feature"  # the feature's identifying code
    DIM = "dim"
    VALUE = "value"


class AttributeColumns:
    """Columns on the `set_exp_attributes` table."""

    ID = "Id"
    CODE = "code"
    EXPERIMENT = "experiment"
    ATTRIBUTE = "attribute"  # the attribute's identifying code
    DIM = "dim"
    VALUE = "value"


class Status(StrEnum):
    """Experiment lifecycle states."""

    DRAFT = "draft"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Strategy(StrEnum):
    """Dataset strategies — *how* experiments are generated."""

    GRID = "grid"
    DISCOVERY = "discovery"
    EXPLORATION = "exploration"
    INFERENCE = "inference"


class Purpose(StrEnum):
    """Dataset purposes — *what* the experiments are used for."""

    REFERENCE = "reference"
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
