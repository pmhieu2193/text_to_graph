from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    local_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=500)
    entity_type: str = Field(min_length=1, max_length=100)

    description: str | None = Field(
        default=None,
        max_length=2000,
    )

    evidence: str = Field(
        min_length=1,
        max_length=3000,
    )

    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
    )


class ExtractedRelation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    local_id: str = Field(min_length=1, max_length=80)

    subject_local_id: str = Field(
        min_length=1,
        max_length=80,
    )

    object_local_id: str = Field(
        min_length=1,
        max_length=80,
    )

    relation_type: str = Field(
        min_length=1,
        max_length=120,
    )

    description: str | None = Field(
        default=None,
        max_length=2000,
    )

    evidence: str = Field(
        min_length=1,
        max_length=3000,
    )

    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
    )


class ExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[ExtractedEntity] = Field(
        default_factory=list,
        max_length=300,
    )

    relations: list[ExtractedRelation] = Field(
        default_factory=list,
        max_length=600,
    )

    @model_validator(mode="after")
    def validate_local_references(self):
        entity_ids = [
            entity.local_id
            for entity in self.entities
        ]

        relation_ids = [
            relation.local_id
            for relation in self.relations
        ]

        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError(
                "Entity local_id must be unique within a chunk."
            )

        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError(
                "Relation local_id must be unique within a chunk."
            )

        known_entity_ids = set(entity_ids)

        for relation in self.relations:
            if relation.subject_local_id not in known_entity_ids:
                raise ValueError(
                    f"Unknown subject: {relation.subject_local_id}"
                )

            if relation.object_local_id not in known_entity_ids:
                raise ValueError(
                    f"Unknown object: {relation.object_local_id}"
                )

        return self