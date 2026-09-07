"""convert scores enums

Revision ID: ea9883f8b469
Revises: 29a72b8fa4d7
Create Date: 2026-09-08 10:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ea9883f8b469"
down_revision: str | Sequence[str] | None = "29a72b8fa4d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Shared by all 12 "Original/Kopie/Original-Kopie" columns -- see
# app.db.models.score's _ART_ENUM for the model-side twin of this object.
# soinstr1art..soinstr4art deliberately do NOT get this type: despite the
# "art" name, they have no CheckConstraint even before this slice
# (confirmed free-text fields, see app.services.score_fields) and stay
# plain varchar.
score_art_enum = postgresql.ENUM(
    "Original", "Kopie", "Original/Kopie", name="score_art", create_type=False
)

score_inhalt_enum = postgresql.ENUM(
    "Orchestermaterial",
    "Chormaterial",
    "Orch-/Chormaterial",
    "Klavierauszug",
    "Orgelauszug",
    "Partitur",
    "Singstimme",
    name="score_inhalt",
    create_type=False,
)

score_sparte_enum = postgresql.ENUM(
    "Advent/Weihnacht",
    "Bundeshymne",
    "Chor",
    "Lied",
    "Messe",
    "Oratorium",
    "Orch/Harfe",
    "Orch/Orgel",
    "Orch/Sakral",
    "Orch/Sol/Chor",
    "Orchester",
    "Passion",
    "Sakral",
    "Sakral/Solo",
    "Symphonie",
    "Volkslied",
    name="score_sparte",
    create_type=False,
)

_ART_COLUMNS = (
    "part1art",
    "part2art",
    "klausz1art",
    "klausz2art",
    "chorpart1art",
    "chorpart2art",
    "stsoprart",
    "staltart",
    "sttenart",
    "stbassart",
    "orgelart",
    "orchart",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("scores_inhalt_check", "scores", type_="check")
    op.drop_constraint("scores_sparte_check", "scores", type_="check")
    for column_name in _ART_COLUMNS:
        op.drop_constraint(f"scores_{column_name}_check", "scores", type_="check")

    score_art_enum.create(op.get_bind(), checkfirst=False)
    score_inhalt_enum.create(op.get_bind(), checkfirst=False)
    score_sparte_enum.create(op.get_bind(), checkfirst=False)

    op.alter_column(
        "scores",
        "inhalt",
        existing_type=sa.String(),
        type_=score_inhalt_enum,
        postgresql_using="inhalt::score_inhalt",
        existing_nullable=True,
    )
    op.alter_column(
        "scores",
        "sparte",
        existing_type=sa.String(),
        type_=score_sparte_enum,
        postgresql_using="sparte::score_sparte",
        existing_nullable=True,
    )
    for column_name in _ART_COLUMNS:
        op.alter_column(
            "scores",
            column_name,
            existing_type=sa.String(),
            type_=score_art_enum,
            postgresql_using=f"{column_name}::score_art",
            existing_nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for column_name in _ART_COLUMNS:
        op.alter_column(
            "scores",
            column_name,
            existing_type=score_art_enum,
            type_=sa.String(),
            postgresql_using=f"{column_name}::varchar",
            existing_nullable=True,
        )
    op.alter_column(
        "scores",
        "sparte",
        existing_type=score_sparte_enum,
        type_=sa.String(),
        postgresql_using="sparte::varchar",
        existing_nullable=True,
    )
    op.alter_column(
        "scores",
        "inhalt",
        existing_type=score_inhalt_enum,
        type_=sa.String(),
        postgresql_using="inhalt::varchar",
        existing_nullable=True,
    )

    score_sparte_enum.drop(op.get_bind(), checkfirst=False)
    score_inhalt_enum.drop(op.get_bind(), checkfirst=False)
    score_art_enum.drop(op.get_bind(), checkfirst=False)

    op.create_check_constraint(
        "scores_inhalt_check",
        "scores",
        "inhalt IN ('Orchestermaterial', 'Chormaterial', "
        "'Orch-/Chormaterial', 'Klavierauszug', 'Orgelauszug', "
        "'Partitur', 'Singstimme')",
    )
    op.create_check_constraint(
        "scores_sparte_check",
        "scores",
        "sparte IN ('Advent/Weihnacht', 'Bundeshymne', 'Chor', 'Lied', "
        "'Messe', 'Oratorium', 'Orch/Harfe', 'Orch/Orgel', "
        "'Orch/Sakral', 'Orch/Sol/Chor', 'Orchester', 'Passion', "
        "'Sakral', 'Sakral/Solo', 'Symphonie', 'Volkslied')",
    )
    for column_name in _ART_COLUMNS:
        op.create_check_constraint(
            f"scores_{column_name}_check",
            "scores",
            f"{column_name} IN ('Original', 'Kopie', 'Original/Kopie')",
        )
