from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObjectSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_name: str = Field(alias="schema", min_length=1)
    name: str = Field(min_length=1)
    columns: list[str] = Field(min_length=1)
    row_limit: int | None = Field(default=10000, ge=1)

    @model_validator(mode="after")
    def unique_columns(self):
        if any(not c for c in self.columns) or len(set(self.columns)) != len(self.columns):
            raise ValueError("Les colonnes doivent être non vides et uniques.")
        return self


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_label: str = Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    batch_size: int = Field(default=10000, ge=1, le=100000)
    objects: list[ObjectSelection] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_objects(self):
        keys = [(o.schema_name, o.name) for o in self.objects]
        if len(keys) != len(set(keys)):
            raise ValueError("Objet sélectionné plusieurs fois.")
        return self
