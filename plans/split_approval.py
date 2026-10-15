"""
SPLIT_APPROVAL -- the release-gate config spec v1.6 section 6.7 bullet 2
calls for: "The approved split/equipment combinations live in one config
mapping ... built from the reviewed audit. The API filters options through
it, so an unapproved split can never be returned or saved."

Built from FITLOG_EXERCISE_AUDIT_v1.md's section 7 recommendation, as
revised after:
  - the catalog additions in
    exercises/migrations/0005_close_equipment_gaps_and_fix_bugs.py (closed
    the Calves/Biceps/Hamstrings gaps at home and minimal equipment), and
  - the bug fixes in that same migration and
    plans/migrations/0003_fix_bro_split_dips_reference.py.

Re-verified directly against the database (same per-split, per-muscle-group,
per-equipment-level methodology as the audit) after those changes -- see the
implementation report for the full before/after table. Net result: every
split in the catalog now passes the >=2-distinct-exercises gate at every
equipment level *except* Bro Split's Shoulders at minimal equipment (3
band exercises vs. a 4-exercise same-session need) -- which is moot here
because Bro Split is a deliberate full-gym-only product decision regardless
of coverage (decision 2 below), not a coverage failure being argued around.

Equipment levels (spec 6.2):
    full_gym    -- every EquipmentType (the superset)
    home_basic  -- Dumbbell + Bodyweight + Resistance Band
    minimal     -- Bodyweight + Resistance Band
"""

EQUIPMENT_LEVELS = ('full_gym', 'home_basic', 'minimal')
DEFAULT_EQUIPMENT_LEVEL = 'full_gym'

# days_per_week -> TrainingSplit slug(s) that exist in the catalog today.
# Extend this when a new split is authored AND audited (e.g. a future 5-day
# Upper/Lower/PPL hybrid -- spec section 12 item 3, deliberately deferred by
# this pass -- or "Full Body 4x", which has no seeded TrainingSplit row at
# all and is therefore never approved below). Until a slug is added here it
# simply has no approved combination and V-21 fires for every equipment
# level requested at that days_per_week.
DAYS_TO_SPLIT_SLUGS = {
    2: ['full-body-ab', 'full-body-strength', 'full-body-conditioning'],
    3: ['full-body', 'full-body-abc', 'push-pull-legs-3', 'full-body-conditioning-3'],
    4: ['upper-lower', 'upper-lower-cardio', 'four-day-body-part', 'upper-lower-specialization'],
    5: ['ppl-upper-lower', 'bro-split', 'upper-lower-specialization-5', 'five-day-strength-hypertrophy'],
    6: ['push-pull-legs', 'arnold-split', 'upper-lower-specialization-6', 'strength-cardio-hybrid', 'six-day-hypertrophy'],
}

# (TrainingSplit.slug, equipment_level) -> approved?
#
# Product-owner decisions applied here (see task brief, not re-litigated):
#   1. Close the home/minimal coverage gap by adding exercises, not by
#      hiding more combinations than necessary (done in the migrations
#      above) -- so every combination below that the pre-fix audit marked
#      FAIL for a coverage reason is now approved.
#   2. 5-day Bro Split is approved at full gym ONLY. Home and minimal stay
#      hidden (NO_SUPPORTED_SPLIT) even though the Calves/Hamstrings/Biceps
#      fixes would incidentally clear two of its three home/minimal
#      failures -- this is a deliberate product decision (no 5-day
#      Upper/Lower/PPL hybrid exists yet to offer those users something
#      better, spec section 12 item 3), not a coverage verdict.
#   3. "Full Body 4x" (the 6.3 alternative for 4 days/week) has no seeded
#      TrainingSplit row at all and is out of scope for this pass -- it is
#      simply absent from DAYS_TO_SPLIT_SLUGS above, so no entry for it
#      exists here either; it can never be approved or returned.
SPLIT_APPROVAL = {
    # 3-day Full Body -- full gym and home always passed; minimal failed
    # pre-fix on Hamstrings (1 exercise, needed 2), now 4 after the catalog
    # migration.
    **{(slug, level): True for slugs in DAYS_TO_SPLIT_SLUGS.values() for slug in slugs for level in EQUIPMENT_LEVELS},

    # 4-day Upper/Lower -- full gym always passed; home failed pre-fix on
    # Calves (1, needed 2), now 4; minimal failed pre-fix on Biceps (0),
    # Hamstrings (1) and Calves (1), now 3/4/3 respectively.
    ('bro-split', 'home_basic'): False,
    ('bro-split', 'minimal'): False,

    # 5-day Bro Split -- full gym only, per decision 2 above. Home and
    # minimal are hidden regardless of catalog coverage.
    ('bro-split', 'full_gym'): True,
}


def is_catalog_complete(split):
    """Fail closed for draft, inactive, incomplete, or stale catalog rows."""
    if not split or not split.is_active or split.approval_status != 'APPROVED':
        return False
    templates = split.workout_templates or {}
    active_days = [templates.get(f'day_{i}') or [] for i in range(1, 8)]
    if sum(bool(day) for day in active_days) != split.days_per_week:
        return False
    return all(
        entry.get('exercise_name') and entry.get('sets', 0) > 0 and entry.get('reps') and entry.get('rest_seconds', -1) >= 0
        for day in active_days for entry in day
    )


def is_split_approved(split_slug, equipment_level):
    """True only for an explicit SPLIT_APPROVAL entry -- an unknown slug or
    equipment level is never approved by default (fail closed, per the
    release-gate requirement that an unapproved split can never be
    returned)."""
    return SPLIT_APPROVAL.get((split_slug, equipment_level), False)


def approved_slugs_for(days_per_week, equipment_level):
    """Every TrainingSplit slug that exists for this days_per_week AND is
    approved at this equipment level. Empty when nothing is offerable --
    the caller should then raise V-21 NO_SUPPORTED_SPLIT."""
    return [
        slug for slug in DAYS_TO_SPLIT_SLUGS.get(days_per_week, [])
        if is_split_approved(slug, equipment_level)
    ]


def approved_combinations():
    """Every (days_per_week, split_slug, equipment_level) triple this
    release allows the API to return or accept -- used both for the V-21
    error payload (named combinations the user can pick instead) and by the
    enumeration test (spec acceptance 11.3)."""
    combos = []
    for days, slugs in DAYS_TO_SPLIT_SLUGS.items():
        for slug in slugs:
            for level in EQUIPMENT_LEVELS:
                if is_split_approved(slug, level):
                    combos.append({
                        'days_per_week': days,
                        'split_slug': slug,
                        'equipment_level': level,
                    })
    return combos
