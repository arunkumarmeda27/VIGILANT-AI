import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_DOCUMENT_TYPE_ID = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_SCHEMA_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_FIELD_ID = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class RegistryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NormalizationConfig(RegistryInput):
    trim: bool = True
    case: Literal["preserve", "upper", "lower"] = "preserve"
    remove_whitespace: bool = False


class FieldConstraints(RegistryInput):
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    pattern: Optional[str] = Field(default=None, max_length=500)
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    min_items: Optional[int] = Field(default=None, ge=0)
    max_items: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
            raise ValueError("min_length cannot exceed max_length")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if self.min_items is not None and self.max_items is not None and self.min_items > self.max_items:
            raise ValueError("min_items cannot exceed max_items")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError("pattern must be a valid regular expression") from exc
        return self


PrimitiveType = Literal["string", "integer", "number", "boolean", "date", "datetime"]


class SchemaFieldDefinition(RegistryInput):
    id: str
    label: str = Field(min_length=1, max_length=255)
    data_type: Literal[
        "string", "integer", "number", "boolean", "date", "datetime", "enum", "array", "object"
    ]
    required: bool = False
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)
    constraints: FieldConstraints = Field(default_factory=FieldConstraints)
    enum_values: Optional[list[str]] = None
    items_type: Optional[PrimitiveType] = None
    object_properties: Optional[dict[str, PrimitiveType]] = None
    object_required_properties: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not _FIELD_ID.fullmatch(value):
            raise ValueError("field id must use lowercase letters, digits, or underscores")
        return value

    @field_validator("enum_values")
    @classmethod
    def validate_enum_values(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is not None and (
            not value
            or any(not item.strip() for item in value)
            or len({item.casefold() for item in value}) != len(value)
        ):
            raise ValueError("enum_values must contain unique, non-empty values")
        return value

    @model_validator(mode="after")
    def validate_field_configuration(self):
        if self.data_type == "enum" and not self.enum_values:
            raise ValueError("enum fields require enum_values")
        if self.data_type != "enum" and self.enum_values is not None:
            raise ValueError("enum_values are only supported for enum fields")
        if self.data_type == "array" and self.items_type is None:
            raise ValueError("array fields require items_type")
        if self.data_type != "array" and self.items_type is not None:
            raise ValueError("items_type is only supported for array fields")
        if self.data_type == "object" and not self.object_properties:
            raise ValueError("object fields require object_properties")
        if self.data_type != "object" and self.object_properties is not None:
            raise ValueError("object_properties are only supported for object fields")
        if self.object_properties and any(
            not _FIELD_ID.fullmatch(key) for key in self.object_properties
        ):
            raise ValueError("object property names must use lowercase letters, digits, or underscores")
        if self.object_required_properties and (
            self.data_type != "object"
            or any(key not in (self.object_properties or {}) for key in self.object_required_properties)
            or len(set(self.object_required_properties)) != len(self.object_required_properties)
        ):
            raise ValueError("object_required_properties must uniquely reference declared object properties")
        if self.data_type != "object" and self.object_required_properties:
            raise ValueError("object_required_properties are only supported for object fields")

        constraints = self.constraints
        if (constraints.min_length is not None or constraints.max_length is not None or constraints.pattern is not None) and self.data_type != "string":
            raise ValueError("length and pattern constraints are only supported for string fields")
        if (constraints.minimum is not None or constraints.maximum is not None) and self.data_type not in {"integer", "number"}:
            raise ValueError("minimum and maximum constraints are only supported for integer or number fields")
        if (constraints.min_items is not None or constraints.max_items is not None) and self.data_type != "array":
            raise ValueError("item-count constraints are only supported for array fields")
        if self.data_type not in {"string", "enum"} and self.normalization != NormalizationConfig():
            raise ValueError("normalization is only supported for string and enum fields")
        return self


class SchemaDefinition(RegistryInput):
    fields: list[SchemaFieldDefinition] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_unique_fields(self):
        ids = [field.id for field in self.fields]
        if len(set(ids)) != len(ids):
            raise ValueError("field ids must be unique within a schema")
        return self


class IssuingAuthorityMetadata(RegistryInput):
    name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    jurisdiction: Optional[str] = Field(default=None, max_length=255)


class VerificationConfiguration(RegistryInput):
    method: Literal["not_configured", "manual_review"] = "not_configured"
    description: Optional[str] = Field(default=None, max_length=1000)


class ExpiryConfiguration(RegistryInput):
    field_id: str
    manual_review_required: bool = True

    @field_validator("field_id")
    @classmethod
    def validate_field_id(cls, value: str) -> str:
        if not _FIELD_ID.fullmatch(value):
            raise ValueError("field_id must use lowercase letters, digits, or underscores")
        return value


class DocumentTypeCreate(RegistryInput):
    id: str
    display_name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=100)
    family: Optional[str] = Field(default=None, max_length=100)
    description: str = Field(min_length=1, max_length=4000)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    supported_file_formats: list[str] = Field(default_factory=lambda: ["pdf"], max_length=20)
    supported_languages: list[str] = Field(default_factory=lambda: ["en"], max_length=50)
    application_categories: list[str] = Field(default_factory=list, max_length=100)
    regulatory_rule_references: list[str] = Field(default_factory=list, max_length=100)
    issuing_authority: Optional[IssuingAuthorityMetadata] = None
    verification_config: VerificationConfiguration = Field(default_factory=VerificationConfiguration)
    expiry_config: Optional[ExpiryConfiguration] = None
    schema_version: str
    schema_definition: SchemaDefinition

    @field_validator("id")
    @classmethod
    def validate_document_type_id(cls, value: str) -> str:
        if not _DOCUMENT_TYPE_ID.fullmatch(value):
            raise ValueError("document type id must use lowercase letters, digits, or underscores")
        return value

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if not _SCHEMA_VERSION.fullmatch(value):
            raise ValueError("schema_version must use semantic version format MAJOR.MINOR.PATCH")
        return value

    @field_validator("supported_file_formats")
    @classmethod
    def validate_file_formats(cls, values: list[str]) -> list[str]:
        normalized = [value.lstrip(".").lower() for value in values]
        if not normalized or any(not re.fullmatch(r"[a-z0-9]{1,10}", value) for value in normalized):
            raise ValueError("supported_file_formats must contain supported file extensions")
        if len(set(normalized)) != len(normalized):
            raise ValueError("supported_file_formats cannot contain duplicates")
        return normalized

    @field_validator("aliases", "application_categories", "regulatory_rule_references")
    @classmethod
    def validate_unique_metadata_values(cls, values: list[str]) -> list[str]:
        if any(not value for value in values) or len({value.casefold() for value in values}) != len(values):
            raise ValueError("metadata values must be non-empty and unique")
        return values

    @field_validator("supported_languages")
    @classmethod
    def validate_languages(cls, values: list[str]) -> list[str]:
        if not values or any(
            not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", value)
            for value in values
        ):
            raise ValueError("supported_languages must contain valid language tags")
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("supported_languages cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_expiry_field(self):
        if self.expiry_config and self.expiry_config.field_id not in {
            field.id for field in self.schema_definition.fields
        }:
            raise ValueError("expiry_config.field_id must refer to a field in schema_definition")
        return self


class SchemaVersionCreate(RegistryInput):
    schema_version: str
    definition: SchemaDefinition

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if not _SCHEMA_VERSION.fullmatch(value):
            raise ValueError("schema_version must use semantic version format MAJOR.MINOR.PATCH")
        return value


class SchemaVersionUpdate(RegistryInput):
    definition: SchemaDefinition


class DocumentTypeMetadataUpdate(RegistryInput):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    family: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set:
            raise ValueError("At least one document type metadata field must be provided")
        if any(
            getattr(self, field) is None
            for field in ("display_name", "category", "description")
            if field in self.model_fields_set
        ):
            raise ValueError("display_name, category, and description cannot be null")
        return self


class DocumentTypeCorrectionCreate(RegistryInput):
    document_type_id: str
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("document_type_id")
    @classmethod
    def validate_document_type_id(cls, value: str) -> str:
        if not _DOCUMENT_TYPE_ID.fullmatch(value):
            raise ValueError("document_type_id must use lowercase letters, digits, or underscores")
        return value


class DocumentTypeOut(BaseModel):
    id: str
    display_name: str
    category: str
    family: Optional[str]
    description: str
    aliases: list[str]
    supported_file_formats: list[str]
    supported_languages: list[str]
    application_categories: list[str]
    regulatory_rule_references: list[str]
    issuing_authority: Optional[dict[str, Any]]
    verification_config: Optional[dict[str, Any]]
    expiry_config: Optional[dict[str, Any]]
    status: str
    schema_versions: list[dict[str, Any]]


class SchemaValidationOut(BaseModel):
    status: str
    schema_version_id: Optional[int]
    fields: list[dict[str, Any]]
    unlisted_extracted_fields: list[str]
