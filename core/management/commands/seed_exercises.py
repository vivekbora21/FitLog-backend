"""
Seed the global exercise catalog with real-world exercises used in strength
training, bodybuilding, powerlifting, and general fitness.

Run this BEFORE any user-specific seed commands so that exercise slugs are
consistent across the entire application.

Usage:
    python manage.py seed_exercises          # seed everything
    python manage.py seed_exercises --wipe   # delete all exercises first, then re-seed

Idempotent: uses get_or_create on slug, safe to re-run.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from exercises.models import MuscleGroup, EquipmentType, Exercise


# ──────────────────────────────────────────────────────────────────────────────
# Reference data
# ──────────────────────────────────────────────────────────────────────────────

MUSCLE_GROUPS = [
    ("Chest", "chest"),
    ("Back", "back"),
    ("Shoulders", "shoulders"),
    ("Biceps", "biceps"),
    ("Triceps", "triceps"),
    ("Forearms", "forearms"),
    ("Quadriceps", "quadriceps"),
    ("Hamstrings", "hamstrings"),
    ("Glutes", "glutes"),
    ("Calves", "calves"),
    ("Core", "core"),
    ("Traps", "traps"),
    ("Cardio", "cardio"),
]

EQUIPMENT_TYPES = [
    ("Barbell", "barbell"),
    ("Dumbbell", "dumbbell"),
    ("Cable", "cable"),
    ("Machine", "machine"),
    ("Bodyweight", "bodyweight"),
    ("Kettlebell", "kettlebell"),
    ("Resistance Band", "resistance-band"),
    ("EZ-Bar", "ez-bar"),
    ("Smith Machine", "smith-machine"),
    ("Cardio Equipment", "cardio-equipment"),
]

# ──────────────────────────────────────────────────────────────────────────────
# Exercise catalog
# (name, slug, primary_muscle_slug, equipment_slug, instructions)
#
# Slugs are the canonical key — keep them stable across all seed files.
# ──────────────────────────────────────────────────────────────────────────────

EXERCISES = [
    # ═══════════════════════════════════════════════════════════════════════════
    # CHEST
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Barbell Bench Press",
        "barbell-bench-press",
        "chest", "barbell",
        "Lie flat on bench with eyes under the bar. Grip slightly wider than shoulder width. "
        "Unrack, lower bar to mid-chest with elbows at ~45°, press up to lockout. "
        "Keep shoulder blades retracted and feet flat."
    ),
    (
        "Incline Barbell Bench Press",
        "incline-barbell-bench-press",
        "chest", "barbell",
        "Set bench to 30-45°. Lower bar to upper chest/clavicle area. "
        "Press up while keeping shoulder blades pinched. Emphasizes upper pectorals."
    ),
    (
        "Decline Barbell Bench Press",
        "decline-barbell-bench-press",
        "chest", "barbell",
        "Set bench to -15° decline. Lower bar to lower chest. "
        "Press up, focusing on lower pectoral fibers. Use a spotter or safety pins."
    ),
    (
        "Dumbbell Bench Press",
        "dumbbell-bench-press",
        "chest", "dumbbell",
        "Lie flat, press dumbbells from chest level to lockout with palms facing forward. "
        "Greater range of motion than barbell variant. Control the descent."
    ),
    (
        "Incline Dumbbell Press",
        "incline-dumbbell-press",
        "chest", "dumbbell",
        "Set incline to 30°. Press dumbbells up over clavicles. "
        "Keep shoulder blades retracted throughout. Targets upper chest."
    ),
    (
        "Decline Dumbbell Press",
        "decline-dumbbell-press",
        "chest", "dumbbell",
        "Press dumbbells from lower chest on a decline bench. "
        "Emphasizes lower pectoral development with dumbbell ROM advantage."
    ),
    (
        "Dumbbell Fly",
        "dumbbell-fly",
        "chest", "dumbbell",
        "Lie flat, arms extended with slight elbow bend. Lower dumbbells in a wide arc "
        "until chest stretch is felt. Squeeze pecs to bring weights together."
    ),
    (
        "Incline Dumbbell Fly",
        "incline-dumbbell-fly",
        "chest", "dumbbell",
        "Same as flat fly but on a 30° incline. Targets upper chest fibers. "
        "Maintain slight elbow bend throughout."
    ),
    (
        "Cable Chest Fly",
        "cable-chest-fly",
        "chest", "cable",
        "Set pulleys at chest height. Step forward, squeeze pecs together "
        "with a slight bend in elbows. Constant cable tension throughout."
    ),
    (
        "Low-to-High Cable Fly",
        "low-to-high-cable-fly",
        "chest", "cable",
        "Set pulleys at lowest position. Sweep arms upward in an arc, "
        "finishing at eye level. Targets upper chest and anterior delt."
    ),
    (
        "High-to-Low Cable Fly",
        "high-to-low-cable-fly",
        "chest", "cable",
        "Set pulleys at highest position. Sweep arms downward in an arc, "
        "finishing at hip level. Targets lower chest fibers."
    ),
    (
        "Pec Deck Machine Fly",
        "pec-deck-machine-fly",
        "chest", "machine",
        "Sit with back flat against pad. Bring handles together with slight elbow bend. "
        "Squeeze pecs at peak, control the return. Isolated chest work."
    ),
    (
        "Machine Chest Press",
        "machine-chest-press",
        "chest", "machine",
        "Sit with back flat against pad, grip handles at chest height. "
        "Press forward to full extension. Good for beginners or burnout sets."
    ),
    (
        "Push-Up",
        "push-up",
        "chest", "bodyweight",
        "Hands shoulder-width apart, body in straight plank. Lower chest to ground, "
        "push back up. Keep core braced throughout. Scale with incline/decline."
    ),
    (
        "Diamond Push-Up",
        "diamond-push-up",
        "chest", "bodyweight",
        "Hands close together forming a diamond shape under chest. "
        "Lower and press up. Shifts emphasis to inner chest and triceps."
    ),
    (
        "Dips (Chest Focus)",
        "chest-dips",
        "chest", "bodyweight",
        "Lean torso forward 30°, flare elbows slightly. Lower until shoulder stretch, "
        "press up focusing on pectoral contraction. Add weight as needed."
    ),
    (
        "Smith Machine Bench Press",
        "smith-machine-bench-press",
        "chest", "smith-machine",
        "Lie flat under Smith machine bar. Press up along the fixed path. "
        "Good for isolating chest without stabilizer demand."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # BACK
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Conventional Deadlift",
        "conventional-deadlift",
        "back", "barbell",
        "Stand with feet hip-width, grip bar just outside knees. Brace core, "
        "drive through feet, extend hips and knees simultaneously. "
        "Keep bar close to body. Lockout with chest proud."
    ),
    (
        "Sumo Deadlift",
        "sumo-deadlift",
        "back", "barbell",
        "Wide stance with toes pointed out. Grip bar inside knees. "
        "Drive knees out, extend hips. Shorter ROM, more quad/glute emphasis."
    ),
    (
        "Barbell Bent-Over Row",
        "barbell-bent-over-row",
        "back", "barbell",
        "Hinge to 45°, grip bar slightly wider than shoulder width. "
        "Pull to lower ribcage, squeeze scapulae. Control the negative."
    ),
    (
        "Pendlay Row",
        "pendlay-row",
        "back", "barbell",
        "Torso parallel to floor, bar starts from dead stop on ground each rep. "
        "Explosive pull to lower chest, controlled descent back to floor."
    ),
    (
        "T-Bar Row",
        "t-bar-row",
        "back", "machine",
        "Straddle the bar or use a chest-supported T-bar machine. "
        "Pull handle to chest, squeezing mid-back at top. Great for thickness."
    ),
    (
        "Single-Arm Dumbbell Row",
        "single-arm-dumbbell-row",
        "back", "dumbbell",
        "One knee and hand on bench for support. Row dumbbell to hip pocket, "
        "retracting shoulder blade. Full stretch at bottom."
    ),
    (
        "Chest-Supported Dumbbell Row",
        "chest-supported-dumbbell-row",
        "back", "dumbbell",
        "Lie face-down on incline bench. Row both dumbbells simultaneously. "
        "Eliminates lower-back involvement for pure lat/rhomboid work."
    ),
    (
        "Seated Cable Row",
        "seated-cable-row",
        "back", "cable",
        "Sit with feet on platform, knees slightly bent. Pull handle to lower ribs, "
        "squeezing shoulder blades together. Extend arms fully on the eccentric."
    ),
    (
        "Close-Grip Seated Cable Row",
        "close-grip-cable-row",
        "back", "cable",
        "Use a V-grip or close-grip handle. Pull to navel, emphasizing rhomboids "
        "and lower lats. Maintain upright torso."
    ),
    (
        "Wide-Grip Lat Pulldown",
        "wide-grip-lat-pulldown",
        "back", "cable",
        "Grip bar wider than shoulders, pull to upper chest. "
        "Drive elbows down and back. Lean slightly back. Targets lat width."
    ),
    (
        "Close-Grip Lat Pulldown",
        "close-grip-lat-pulldown",
        "back", "cable",
        "Use V-grip or narrow handle. Pull to upper chest. "
        "Greater ROM and biceps involvement than wide-grip variant."
    ),
    (
        "Neutral-Grip Lat Pulldown",
        "neutral-grip-lat-pulldown",
        "back", "cable",
        "Palms facing each other. Pull to upper chest, elbows tucked. "
        "Balanced lat engagement, comfortable shoulder position."
    ),
    (
        "Straight-Arm Lat Pulldown",
        "straight-arm-lat-pulldown",
        "back", "cable",
        "Stand facing cable tower, arms extended. Pull bar down to thighs "
        "in an arc, keeping arms straight. Isolates lats."
    ),
    (
        "Pull-Up",
        "pull-up",
        "back", "bodyweight",
        "Pronated grip wider than shoulders. Pull chest to bar, controlling descent. "
        "Dead hang at bottom. Add weight once bodyweight is manageable."
    ),
    (
        "Chin-Up",
        "chin-up",
        "back", "bodyweight",
        "Supinated shoulder-width grip. Pull chin above bar, driving elbows down. "
        "More biceps emphasis than pull-ups."
    ),
    (
        "Inverted Row",
        "inverted-row",
        "back", "bodyweight",
        "Hang under a bar at waist height. Pull chest to bar with body straight. "
        "Excellent beginner pull exercise and horizontal row substitute."
    ),
    (
        "Machine Seated Row",
        "machine-seated-row",
        "back", "machine",
        "Use a plate-loaded or selectorized row machine. Pull handles to torso, "
        "squeeze scapulae. Stable setup for back hypertrophy."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # SHOULDERS
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Overhead Barbell Press (OHP)",
        "overhead-barbell-press",
        "shoulders", "barbell",
        "Standing with bar at collarbone. Press overhead to lockout, "
        "tucking chin to let bar pass. Core and glutes braced."
    ),
    (
        "Seated Dumbbell Shoulder Press",
        "seated-dumbbell-shoulder-press",
        "shoulders", "dumbbell",
        "Sit on upright bench. Press dumbbells from shoulder height to lockout. "
        "Keep core tight and back against pad."
    ),
    (
        "Arnold Press",
        "arnold-press",
        "shoulders", "dumbbell",
        "Start with dumbbells at chin, palms facing you. Rotate palms outward "
        "as you press overhead. Hits all three delt heads through rotation."
    ),
    (
        "Dumbbell Lateral Raise",
        "dumbbell-lateral-raise",
        "shoulders", "dumbbell",
        "Stand with dumbbells at sides. Raise arms out to shoulder height "
        "leading with elbows. Pause at top, control descent. Targets medial delts."
    ),
    (
        "Cable Lateral Raise",
        "cable-lateral-raise",
        "shoulders", "cable",
        "Stand side-on to low pulley. Raise arm to shoulder height, "
        "maintaining constant tension. Great for medial delt isolation."
    ),
    (
        "Dumbbell Front Raise",
        "dumbbell-front-raise",
        "shoulders", "dumbbell",
        "Raise dumbbells in front of body to shoulder height. "
        "Alternate arms or raise together. Targets anterior deltoid."
    ),
    (
        "Cable Face Pull",
        "cable-face-pull",
        "shoulders", "cable",
        "Set cable at upper-chest height with rope attachment. Pull towards face "
        "with elbows high, externally rotating at the end. Rear delt + rotator cuff."
    ),
    (
        "Dumbbell Rear Delt Fly",
        "dumbbell-rear-delt-fly",
        "shoulders", "dumbbell",
        "Hinged at hips or chest-supported on bench. Raise dumbbells out to sides "
        "with slight elbow bend. Targets posterior deltoids."
    ),
    (
        "Reverse Pec Deck Fly",
        "reverse-pec-deck-fly",
        "shoulders", "machine",
        "Sit facing the pec deck machine. Push handles back with arms extended, "
        "squeezing rear delts and rhomboids. Clean scapular retraction."
    ),
    (
        "Machine Shoulder Press",
        "machine-shoulder-press",
        "shoulders", "machine",
        "Sit in shoulder press machine, push handles overhead. "
        "Stable pressing movement for shoulder hypertrophy."
    ),
    (
        "Barbell Upright Row",
        "barbell-upright-row",
        "shoulders", "barbell",
        "Grip bar narrow, pull up along body to chin level. Elbows lead the movement. "
        "Targets traps and medial delts. Avoid if shoulder impingement is an issue."
    ),
    (
        "Dumbbell Shrug",
        "dumbbell-shrug",
        "traps", "dumbbell",
        "Hold heavy dumbbells at sides. Shrug shoulders straight up toward ears. "
        "Hold at top for 1 second. Targets upper trapezius."
    ),
    (
        "Barbell Shrug",
        "barbell-shrug",
        "traps", "barbell",
        "Hold barbell at thighs with overhand grip. Shrug shoulders upward. "
        "Keep arms straight throughout. Heavy loading for trap development."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # BICEPS
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Barbell Bicep Curl",
        "barbell-bicep-curl",
        "biceps", "barbell",
        "Stand with barbell, shoulder-width supinated grip. Curl bar up "
        "without swinging torso. Squeeze at top, control descent."
    ),
    (
        "EZ-Bar Curl",
        "ez-bar-curl",
        "biceps", "ez-bar",
        "Use angled EZ-bar grip for wrist comfort. Curl with strict form, "
        "keeping elbows pinned to sides. Full range of motion."
    ),
    (
        "Dumbbell Bicep Curl",
        "dumbbell-bicep-curl",
        "biceps", "dumbbell",
        "Standing or seated, curl dumbbells with supinated grip. "
        "Alternate arms or curl together. No body English."
    ),
    (
        "Incline Dumbbell Curl",
        "incline-dumbbell-curl",
        "biceps", "dumbbell",
        "Sit on 45° incline bench. Curl dumbbells from full stretch position. "
        "Long head of biceps is maximally stretched at the bottom."
    ),
    (
        "Hammer Curl",
        "hammer-curl",
        "biceps", "dumbbell",
        "Neutral (palms facing each other) grip curls. Targets brachialis "
        "and brachioradialis. Builds forearm thickness."
    ),
    (
        "Concentration Curl",
        "concentration-curl",
        "biceps", "dumbbell",
        "Sit on bench, brace elbow against inner thigh. Curl dumbbell, "
        "squeezing bicep hard at top. Pure isolation movement."
    ),
    (
        "Preacher Curl",
        "preacher-curl",
        "biceps", "ez-bar",
        "Rest upper arms on preacher pad. Curl EZ-bar up, preventing momentum. "
        "Isolates biceps peak contraction."
    ),
    (
        "Cable Bicep Curl",
        "cable-bicep-curl",
        "biceps", "cable",
        "Stand facing low cable with straight bar. Curl up with constant tension. "
        "Good for drop sets and high-rep work."
    ),
    (
        "Spider Curl",
        "spider-curl",
        "biceps", "dumbbell",
        "Lie face-down on incline bench, arms hanging straight down. "
        "Curl dumbbells up. Eliminates cheating, pure biceps contraction."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # TRICEPS
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Close-Grip Bench Press",
        "close-grip-bench-press",
        "triceps", "barbell",
        "Hands shoulder-width or narrower on barbell. Lower to lower chest, "
        "press up focusing on triceps lockout. Keep elbows tucked."
    ),
    (
        "Tricep Rope Pushdown",
        "tricep-rope-pushdown",
        "triceps", "cable",
        "Attach rope to high cable. Pin elbows to sides, push down and "
        "spread rope ends apart at bottom. Squeeze triceps hard."
    ),
    (
        "Straight Bar Tricep Pushdown",
        "straight-bar-tricep-pushdown",
        "triceps", "cable",
        "Attach straight bar to high cable. Push down with overhand grip, "
        "locking out elbows. Control the negative."
    ),
    (
        "V-Bar Tricep Pushdown",
        "v-bar-tricep-pushdown",
        "triceps", "cable",
        "Use V-shaped attachment on high cable. Clean lockouts at bottom "
        "with elbows tucked. Targets lateral and medial heads."
    ),
    (
        "Overhead Cable Tricep Extension",
        "overhead-cable-tricep-extension",
        "triceps", "cable",
        "Face away from cable tower with rope attachment overhead. "
        "Extend arms forward, stretching long head of triceps."
    ),
    (
        "Skull Crusher (Lying Tricep Extension)",
        "skull-crusher",
        "triceps", "ez-bar",
        "Lie flat, lower EZ-bar to forehead or just behind head. "
        "Extend arms to lockout. Deep stretch on triceps long head."
    ),
    (
        "Dumbbell Overhead Tricep Extension",
        "dumbbell-overhead-extension",
        "triceps", "dumbbell",
        "Hold single dumbbell overhead with both hands. Lower behind head, "
        "elbows pointing up. Extend back to lockout. Long head emphasis."
    ),
    (
        "Single-Arm Dumbbell Overhead Extension",
        "single-arm-overhead-extension",
        "triceps", "dumbbell",
        "Hold one dumbbell overhead. Lower behind head with elbow fixed. "
        "Extend back up. Isolates each arm independently."
    ),
    (
        "Tricep Dips",
        "tricep-dips",
        "triceps", "bodyweight",
        "Upright torso on parallel bars or bench. Lower until upper arms "
        "are parallel to floor. Press up with tricep focus. Keep elbows in."
    ),
    (
        "Diamond Push-Up (Tricep Focus)",
        "diamond-push-up-triceps",
        "triceps", "bodyweight",
        "Hands together under chest forming diamond. Lower and press up. "
        "Significant triceps emphasis over standard push-up."
    ),
    (
        "Tricep Kickback",
        "tricep-kickback",
        "triceps", "dumbbell",
        "Hinge at hips, upper arm parallel to torso. Extend dumbbell back "
        "to full lockout. Squeeze triceps at peak contraction."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # FOREARMS
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Barbell Wrist Curl",
        "barbell-wrist-curl",
        "forearms", "barbell",
        "Sit with forearms on thighs, palms up. Curl barbell using only wrist flexion. "
        "Full range from extension to flexion."
    ),
    (
        "Reverse Barbell Wrist Curl",
        "reverse-barbell-wrist-curl",
        "forearms", "barbell",
        "Same position but palms facing down. Extend wrists upward. "
        "Targets wrist extensors for balanced forearm development."
    ),
    (
        "Farmer's Walk",
        "farmers-walk",
        "forearms", "dumbbell",
        "Hold heavy dumbbells at sides. Walk for distance or time with upright posture. "
        "Grip, core, and trap endurance."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # QUADRICEPS
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Barbell Back Squat",
        "barbell-back-squat",
        "quadriceps", "barbell",
        "Bar across upper traps (high bar) or rear delts (low bar). "
        "Break at hips and knees, descend to at least parallel. Drive up through heels."
    ),
    (
        "Barbell Front Squat",
        "barbell-front-squat",
        "quadriceps", "barbell",
        "Bar in clean rack position with high elbows. Maintain vertical torso. "
        "Greater quad emphasis than back squat."
    ),
    (
        "Goblet Squat",
        "goblet-squat",
        "quadriceps", "dumbbell",
        "Hold dumbbell or kettlebell at chest. Squat between legs to depth. "
        "Excellent for learning squat mechanics and quad activation."
    ),
    (
        "Leg Press",
        "leg-press",
        "quadriceps", "machine",
        "Feet shoulder-width on platform. Lower sled until knees form 90°. "
        "Press through heels. Don't lock out knees at top."
    ),
    (
        "Hack Squat",
        "hack-squat",
        "quadriceps", "machine",
        "Shoulders under pads, feet forward on platform. Squat down with "
        "controlled eccentric. Excellent quad isolation without spinal loading."
    ),
    (
        "Leg Extension",
        "leg-extension",
        "quadriceps", "machine",
        "Sit with knees at edge of seat. Extend legs to full lockout. "
        "Pause 1 second at top. Isolates quadriceps."
    ),
    (
        "Bulgarian Split Squat",
        "bulgarian-split-squat",
        "quadriceps", "dumbbell",
        "Rear foot elevated on bench. Lunge down until rear knee nearly touches floor. "
        "Unilateral quad, glute, and balance developer."
    ),
    (
        "Walking Lunge",
        "walking-lunge",
        "quadriceps", "dumbbell",
        "Step forward into deep lunge, drive through front heel to step forward "
        "with next leg. Keep torso upright throughout."
    ),
    (
        "Sissy Squat",
        "sissy-squat",
        "quadriceps", "bodyweight",
        "Hold support, lean back and bend knees, pushing them forward. "
        "Extreme quad stretch and isolation. Advanced movement."
    ),
    (
        "Smith Machine Squat",
        "smith-machine-squat",
        "quadriceps", "smith-machine",
        "Feet slightly forward, squat in guided bar path. "
        "Good for isolating quads with less stabilizer demand."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # HAMSTRINGS
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Romanian Deadlift (RDL)",
        "romanian-deadlift",
        "hamstrings", "barbell",
        "Stand with bar at thighs. Hinge at hips, pushing them back. "
        "Keep knees slightly bent. Lower until hamstring stretch is deep. "
        "Reverse by driving hips forward."
    ),
    (
        "Dumbbell Romanian Deadlift",
        "dumbbell-romanian-deadlift",
        "hamstrings", "dumbbell",
        "Same hinge pattern as barbell RDL but with dumbbells at sides. "
        "Allows freer movement path and can be done unilaterally."
    ),
    (
        "Single-Leg Romanian Deadlift",
        "single-leg-rdl",
        "hamstrings", "dumbbell",
        "Stand on one leg, hinge forward while extending opposite leg back. "
        "Unilateral hamstring and glute work with balance challenge."
    ),
    (
        "Lying Leg Curl",
        "lying-leg-curl",
        "hamstrings", "machine",
        "Lie face-down, dorsiflex ankles, curl pad towards glutes. "
        "Squeeze at top, control the negative. Isolates knee flexion."
    ),
    (
        "Seated Leg Curl",
        "seated-leg-curl",
        "hamstrings", "machine",
        "Sit with thigh pad securing legs. Curl pad under calves toward glutes. "
        "Isolates hamstrings in a lengthened position."
    ),
    (
        "Nordic Hamstring Curl",
        "nordic-hamstring-curl",
        "hamstrings", "bodyweight",
        "Kneel with ankles secured. Lower body forward under control using "
        "hamstrings as brakes. Catch with hands and push back up."
    ),
    (
        "Good Morning",
        "good-morning",
        "hamstrings", "barbell",
        "Bar on upper back. Hinge at hips keeping back flat. "
        "Feel deep hamstring stretch. Extend back up. Also targets erectors."
    ),
    (
        "Glute-Ham Raise (GHR)",
        "glute-ham-raise",
        "hamstrings", "machine",
        "On GHD machine, lower torso with knees on pad. Use hamstrings "
        "to pull body back up. One of the best hamstring exercises."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # GLUTES
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Barbell Hip Thrust",
        "barbell-hip-thrust",
        "glutes", "barbell",
        "Upper back on bench, barbell across hips with pad. "
        "Drive through heels to full hip extension. Squeeze glutes at top. "
        "The gold-standard glute builder."
    ),
    (
        "Glute Bridge",
        "glute-bridge",
        "glutes", "bodyweight",
        "Lie on back, feet flat, knees bent. Drive hips up squeezing glutes. "
        "Hold at top for 2 seconds. Can be loaded with dumbbell or barbell."
    ),
    (
        "Cable Pull-Through",
        "cable-pull-through",
        "glutes", "cable",
        "Face away from low cable. Hinge at hips letting rope pass between legs. "
        "Extend hips forward, squeezing glutes at the top."
    ),
    (
        "Cable Kickback",
        "cable-kickback",
        "glutes", "cable",
        "Attach ankle strap to low cable. Kick leg back, squeezing glute "
        "at full extension. Keep core tight and avoid arching back."
    ),
    (
        "Step-Up",
        "dumbbell-step-up",
        "glutes", "dumbbell",
        "Hold dumbbells, step onto elevated platform (16-20 inches). "
        "Drive through front foot, bring rear foot up. Step back down with control."
    ),
    (
        "Sumo Squat",
        "sumo-squat",
        "glutes", "dumbbell",
        "Wide stance, toes pointed out 45°. Hold dumbbell or kettlebell at center. "
        "Squat deep, driving knees out. Targets inner thighs and glutes."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # CALVES
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Standing Calf Raise",
        "standing-calf-raise",
        "calves", "machine",
        "Shoulders under pads, balls of feet on platform edge. "
        "Rise up through full ankle extension. Slow 3-second stretch at bottom."
    ),
    (
        "Seated Calf Raise",
        "seated-calf-raise",
        "calves", "machine",
        "Sit with knees under pad, balls of feet on platform. "
        "Raise heels up, squeezing calves. Targets soleus muscle."
    ),
    (
        "Single-Leg Calf Raise",
        "single-leg-calf-raise",
        "calves", "bodyweight",
        "Stand on one foot on raised surface. Rise up on toes, lower slowly. "
        "Addresses calf imbalances. Hold dumbbell for added resistance."
    ),
    (
        "Donkey Calf Raise",
        "donkey-calf-raise",
        "calves", "machine",
        "Bend at hips with pad on lower back. Rise on toes from stretched position. "
        "Deep stretch through gastrocnemius."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # CORE / ABS
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Hanging Leg Raise",
        "hanging-leg-raise",
        "core", "bodyweight",
        "Hang from pull-up bar. Raise straight legs to 90° (or toes to bar). "
        "Control the descent. Advanced: avoid swinging."
    ),
    (
        "Hanging Knee Raise",
        "hanging-knee-raise",
        "core", "bodyweight",
        "Hang from bar, raise knees to chest. More accessible than straight-leg "
        "variant. Great for lower abs."
    ),
    (
        "Ab Wheel Rollout",
        "ab-wheel-rollout",
        "core", "bodyweight",
        "Kneeling on floor, grip ab wheel. Roll forward extending body, "
        "then pull back using abs. Keep hips from sagging."
    ),
    (
        "Cable Crunch",
        "cable-crunch",
        "core", "cable",
        "Kneel facing cable tower, rope behind head. Crunch down "
        "curling torso toward hips. Focus on spinal flexion not hip flexion."
    ),
    (
        "Cable Woodchopper",
        "cable-woodchopper",
        "core", "cable",
        "Set cable high or low. Rotate torso diagonally across body "
        "with straight arms. Targets obliques and rotational core strength."
    ),
    (
        "Plank",
        "plank",
        "core", "bodyweight",
        "Forearms and toes on ground, body in straight line. "
        "Hold position, keeping core braced and hips level. Time-based."
    ),
    (
        "Side Plank",
        "side-plank",
        "core", "bodyweight",
        "Lie on side, prop up on forearm. Keep body straight, hips elevated. "
        "Hold for time. Targets obliques and lateral core stability."
    ),
    (
        "Russian Twist",
        "russian-twist",
        "core", "bodyweight",
        "Sit with knees bent, lean back 45°, feet off ground. "
        "Rotate torso side to side. Hold weight for added resistance."
    ),
    (
        "Sit-Up",
        "sit-up",
        "core", "bodyweight",
        "Lie on back, knees bent, feet anchored. Curl torso up to seated position. "
        "Controlled flexion and extension of the spine."
    ),
    (
        "Crunch",
        "crunch",
        "core", "bodyweight",
        "Lie on back, hands behind head. Curl shoulders off floor "
        "contracting abs. Small range of motion, focus on upper abs."
    ),
    (
        "Bicycle Crunch",
        "bicycle-crunch",
        "core", "bodyweight",
        "Lie on back, alternate bringing opposite elbow to knee in a "
        "pedaling motion. Targets obliques and rectus abdominis."
    ),
    (
        "Ab Machine Crunch",
        "ab-machine-crunch",
        "core", "machine",
        "Sit in ab machine, select weight. Crunch forward with focused "
        "spinal flexion. Good for progressive overloading abs."
    ),
    (
        "Dead Bug",
        "dead-bug",
        "core", "bodyweight",
        "Lie on back, arms extended up, knees at 90°. Slowly extend opposite "
        "arm and leg while maintaining lower back contact with floor."
    ),
    (
        "Pallof Press",
        "pallof-press",
        "core", "cable",
        "Stand side-on to cable at chest height. Press handle straight out, "
        "resisting rotation. Hold for 2 seconds. Anti-rotation core exercise."
    ),
    (
        "Decline Sit-Up",
        "decline-sit-up",
        "core", "bodyweight",
        "Lie on decline bench with feet secured. Curl torso up toward knees. "
        "Increased range of motion and resistance from gravity."
    ),
    (
        "Mountain Climber",
        "mountain-climber",
        "core", "bodyweight",
        "Push-up position, drive knees alternately toward chest rapidly. "
        "Core stability with cardio component."
    ),
    (
        "V-Up",
        "v-up",
        "core", "bodyweight",
        "Lie flat, simultaneously raise legs and torso to touch toes, "
        "forming a V shape. Eccentric control back to flat."
    ),
    (
        "L-Sit Hold",
        "l-sit-hold",
        "core", "bodyweight",
        "Support body on parallel bars or floor with straight arms. "
        "Hold legs extended horizontally. Extreme core and hip flexor demand."
    ),
    (
        "Dragon Flag",
        "dragon-flag",
        "core", "bodyweight",
        "Lie on bench, grip behind head. Raise body to vertical then lower "
        "under control keeping body straight. Advanced core exercise."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # TRAPS (additional)
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Rack Pull",
        "rack-pull",
        "traps", "barbell",
        "Set safety pins at knee height. Deadlift from this position "
        "to lockout. Overloads traps and upper back with heavy weight."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # FULL-BODY / COMPOUND
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Barbell Clean & Press",
        "barbell-clean-and-press",
        "shoulders", "barbell",
        "Clean barbell from floor to shoulders, then press overhead. "
        "Full-body power and coordination movement."
    ),
    (
        "Kettlebell Swing",
        "kettlebell-swing",
        "glutes", "kettlebell",
        "Hinge at hips, swing kettlebell between legs then drive hips forward "
        "to swing to chest height. Explosive hip extension. Power and conditioning."
    ),
    (
        "Turkish Get-Up",
        "turkish-get-up",
        "core", "kettlebell",
        "Start lying down with kettlebell overhead. Move through a precise "
        "sequence to standing while keeping weight overhead. Total body stability."
    ),
    (
        "Kettlebell Goblet Squat",
        "kettlebell-goblet-squat",
        "quadriceps", "kettlebell",
        "Hold kettlebell at chest by horns. Squat deep with elbows inside knees. "
        "Great for squat patterning and quad/glute work."
    ),
    (
        "Thruster",
        "barbell-thruster",
        "shoulders", "barbell",
        "Front squat into immediate overhead press in one fluid motion. "
        "Combines legs and shoulders. Common in CrossFit and conditioning."
    ),
    (
        "Burpee",
        "burpee",
        "core", "bodyweight",
        "Squat down, kick feet back to push-up position, perform push-up, "
        "jump feet forward, and leap up. Full-body conditioning."
    ),
    (
        "Battle Rope Slam",
        "battle-rope-slam",
        "core", "bodyweight",
        "Hold both ends of a heavy rope. Slam ropes up and down alternately "
        "or simultaneously. Cardio, core, and shoulder endurance."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # CARDIO
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Treadmill Running",
        "treadmill-running",
        "cardio", "cardio-equipment",
        "Aerobic or interval running on motorized treadmill. "
        "Control speed and incline based on training goal."
    ),
    (
        "Incline Treadmill Walk",
        "incline-treadmill-walk",
        "cardio", "cardio-equipment",
        "Set treadmill to 10-15% incline, walk at 3-5 mph. "
        "Excellent low-impact fat burning and Zone 2 cardio."
    ),
    (
        "Elliptical Trainer",
        "elliptical-trainer",
        "cardio", "cardio-equipment",
        "Low-impact full-body cardio. Adjust resistance and incline. "
        "Easy on joints while maintaining elevated heart rate."
    ),
    (
        "Stationary Bike",
        "stationary-bike",
        "cardio", "cardio-equipment",
        "Upright or recumbent cycling. Adjust resistance for steady-state "
        "or interval training. Low-impact leg cardio."
    ),
    (
        "Rowing Machine",
        "rowing-machine",
        "cardio", "cardio-equipment",
        "Full-body cardio: drive with legs, hinge hips, pull arms. "
        "Damper setting controls air resistance. Great conditioning tool."
    ),
    (
        "Stairmaster / Stair Climber",
        "stairmaster",
        "cardio", "cardio-equipment",
        "Continuous stair climbing. Targets glutes, quads, and calves "
        "while maintaining elevated heart rate. Moderate-to-hard intensity."
    ),
    (
        "Assault Air Bike",
        "assault-air-bike",
        "cardio", "cardio-equipment",
        "Fan-resistance bike using arms and legs simultaneously. "
        "The harder you go, the harder it gets. Excellent for HIIT."
    ),
    (
        "Jump Rope",
        "jump-rope",
        "cardio", "bodyweight",
        "Skip rope with both feet or alternate feet. "
        "Develops coordination, calf endurance, and cardiovascular fitness."
    ),
    (
        "Sled Push",
        "sled-push",
        "cardio", "machine",
        "Load sled and push it across a surface. Low handles for leg drive, "
        "high handles for overall power. Conditioning and leg strength."
    ),
    (
        "Box Jump",
        "box-jump",
        "cardio", "bodyweight",
        "Explosively jump onto an elevated box or platform. "
        "Land softly with bent knees. Step down. Develops lower body power."
    ),
    (
        "Sprints",
        "sprints",
        "cardio", "bodyweight",
        "All-out running for short distances (50-200m) with rest between sets. "
        "Develops speed, power, and anaerobic capacity."
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # STRETCHING / MOBILITY (commonly logged)
    # ═══════════════════════════════════════════════════════════════════════════
    (
        "Foam Rolling (Full Body)",
        "foam-rolling",
        "core", "bodyweight",
        "Use foam roller on major muscle groups for myofascial release. "
        "30-60 seconds per muscle group. Pre or post workout."
    ),
    (
        "Band Pull-Apart",
        "band-pull-apart",
        "shoulders", "resistance-band",
        "Hold band at shoulder width. Pull apart horizontally, squeezing rear delts. "
        "Excellent warm-up and posture corrector."
    ),
    (
        "Band Face Pull",
        "band-face-pull",
        "shoulders", "resistance-band",
        "Attach band at head height. Pull toward face with external rotation. "
        "Warm-up and prehab for shoulders."
    ),
    (
        "Band Dislocate",
        "band-dislocate",
        "shoulders", "resistance-band",
        "Hold band wide, pass it overhead and behind back in a smooth arc. "
        "Shoulder mobility and rotator cuff warm-up."
    ),
]


class Command(BaseCommand):
    help = (
        "Seeds the global exercise catalog with 150+ real-world exercises, "
        "muscle groups, and equipment types. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--wipe",
            action="store_true",
            help="Delete ALL existing exercises, muscle groups, and equipment before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["wipe"]:
            self.stdout.write(self.style.WARNING("Wiping all exercises, muscle groups, and equipment..."))
            Exercise.objects.all().delete()
            MuscleGroup.objects.all().delete()
            EquipmentType.objects.all().delete()

        # ── Muscle groups ────────────────────────────────────────────────────
        muscles = {}
        for name, slug in MUSCLE_GROUPS:
            obj, created = MuscleGroup.objects.get_or_create(name=name, slug=slug)
            muscles[slug] = obj
            if created:
                self.stdout.write(f"  + MuscleGroup: {name}")

        self.stdout.write(f"  Muscle groups: {len(muscles)} ready.")

        # ── Equipment types ──────────────────────────────────────────────────
        equipments = {}
        for name, slug in EQUIPMENT_TYPES:
            obj, created = EquipmentType.objects.get_or_create(name=name, slug=slug)
            equipments[slug] = obj
            if created:
                self.stdout.write(f"  + EquipmentType: {name}")

        self.stdout.write(f"  Equipment types: {len(equipments)} ready.")

        # ── Exercises ────────────────────────────────────────────────────────
        created_count = 0
        skipped_count = 0
        for name, slug, muscle_slug, equip_slug, instructions in EXERCISES:
            _, created = Exercise.objects.get_or_create(
                slug=slug,
                gym=None,  # Global catalog
                defaults={
                    "name": name,
                    "primary_muscle": muscles[muscle_slug],
                    "equipment": equipments[equip_slug],
                    "instructions": instructions,
                },
            )
            if created:
                created_count += 1
            else:
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nExercise catalog seeded: "
                f"{created_count} created, {skipped_count} already existed, "
                f"{len(EXERCISES)} total in catalog."
            )
        )
