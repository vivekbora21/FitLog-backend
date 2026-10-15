"""Renders a user's full FitLog data as a polished, human-readable PDF report,
for the self-service data export ("Export my data") feature on mobile and web."""
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, PolyLine, String
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE_SIZE = A4
MARGIN_X = 16 * mm

# Brand palette — matches the mobile/web app's emerald accent (theme/tokens.ts).
BRAND = colors.HexColor('#0F766E')
BRAND_DARK = colors.HexColor('#0B5B55')
BRAND_TINT = colors.HexColor('#ECFDF5')
BRAND_TINT_SOFT = colors.HexColor('#F0FDFA')
INK = colors.HexColor('#111827')
MUTED = colors.HexColor('#6B7280')
FAINT = colors.HexColor('#9CA3AF')
BORDER = colors.HexColor('#E5E7EB')
ON_BRAND = colors.white
ON_BRAND_MUTED = colors.HexColor('#D1FAE5')

_STYLES = getSampleStyleSheet()
_BANNER_TITLE = ParagraphStyle('BannerTitle', parent=_STYLES['Normal'], fontName='Helvetica-Bold', fontSize=22, textColor=ON_BRAND, leading=26)
_BANNER_SUB = ParagraphStyle('BannerSub', parent=_STYLES['Normal'], fontName='Helvetica', fontSize=10.5, textColor=ON_BRAND_MUTED, leading=14, spaceBefore=2)
_BANNER_META = ParagraphStyle('BannerMeta', parent=_STYLES['Normal'], fontName='Helvetica-Bold', fontSize=10.5, textColor=ON_BRAND, alignment=TA_RIGHT, leading=14)
_BANNER_META_SUB = ParagraphStyle('BannerMetaSub', parent=_STYLES['Normal'], fontName='Helvetica', fontSize=8.5, textColor=ON_BRAND_MUTED, alignment=TA_RIGHT, leading=12)

_STAT_VALUE = ParagraphStyle('StatValue', parent=_STYLES['Normal'], fontName='Helvetica-Bold', fontSize=16, textColor=BRAND_DARK, alignment=1, leading=19)
_STAT_LABEL = ParagraphStyle('StatLabel', parent=_STYLES['Normal'], fontName='Helvetica', fontSize=7.5, textColor=MUTED, alignment=1, leading=10)

_SECTION_TITLE = ParagraphStyle('SectionTitle', parent=_STYLES['Normal'], fontName='Helvetica-Bold', fontSize=12.5, textColor=INK, spaceBefore=7 * mm, spaceAfter=1.5 * mm)
_EMPTY_STYLE = ParagraphStyle('ExportEmpty', parent=_STYLES['Normal'], fontName='Helvetica-Oblique', fontSize=9, textColor=FAINT, spaceAfter=2 * mm)

_CELL = ParagraphStyle('Cell', parent=_STYLES['Normal'], fontName='Helvetica', fontSize=8.3, textColor=INK, leading=10.5)
_CELL_HEAD = ParagraphStyle('CellHead', parent=_STYLES['Normal'], fontName='Helvetica-Bold', fontSize=8.3, textColor=ON_BRAND, leading=10.5)
_FACT_LABEL = ParagraphStyle('FactLabel', parent=_STYLES['Normal'], fontName='Helvetica', fontSize=9, textColor=MUTED, leading=12)
_FACT_VALUE = ParagraphStyle('FactValue', parent=_STYLES['Normal'], fontName='Helvetica-Bold', fontSize=9, textColor=INK, alignment=TA_RIGHT, leading=12)

_DATA_TABLE_STYLE = TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), BRAND),
    ('TOPPADDING', (0, 0), (-1, 0), 6),
    ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, BRAND_TINT_SOFT]),
    ('LINEBELOW', (0, 0), (-1, -2), 0.5, BORDER),
    ('BOX', (0, 0), (-1, -1), 0.75, BORDER),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ('TOPPADDING', (0, 1), (-1, -1), 4),
    ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
])

_FACT_TABLE_STYLE = TableStyle([
    ('LINEBELOW', (0, 0), (-1, -2), 0.5, BORDER),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('LEFTPADDING', (0, 0), (-1, -1), 2),
    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ('TOPPADDING', (0, 0), (-1, -1), 4.5),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
])

CHART_WIDTH = PAGE_SIZE[0] - 2 * MARGIN_X
CHART_HEIGHT = 36 * mm
_CHART_PAD = {'left': 11 * mm, 'right': 3 * mm, 'top': 4 * mm, 'bottom': 8 * mm}
_CHART_LABEL = ParagraphStyle('ChartLabel', parent=_STYLES['Normal'], fontName='Helvetica', fontSize=8, textColor=MUTED, spaceAfter=1.5 * mm)


def _growth_chart(points, color, value_fmt=None):
    """A branded line/area chart drawn from scratch (no reportlab.graphics.charts, which
    doesn't match the app's visual language). `points`: chronological (date_str, value)
    pairs. Returns a Drawing, or None when there isn't enough history to plot a trend."""
    points = [(d, v) for d, v in points if v is not None]
    if len(points) < 2:
        return None
    value_fmt = value_fmt or (lambda v: f'{v:g}')

    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    if min(values) >= 0:
        lo = max(0, lo)

    plot_w = CHART_WIDTH - _CHART_PAD['left'] - _CHART_PAD['right']
    plot_h = CHART_HEIGHT - _CHART_PAD['top'] - _CHART_PAD['bottom']
    n = len(points)

    def x_at(i):
        return _CHART_PAD['left'] + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)

    def y_at(v):
        return _CHART_PAD['bottom'] + (v - lo) / (hi - lo) * plot_h

    d = Drawing(CHART_WIDTH, CHART_HEIGHT)

    for frac in (0, 0.5, 1):
        y = _CHART_PAD['bottom'] + frac * plot_h
        d.add(Line(_CHART_PAD['left'], y, CHART_WIDTH - _CHART_PAD['right'], y, strokeColor=BORDER, strokeWidth=0.4))
        d.add(String(0, y - 2.3, value_fmt(lo + frac * (hi - lo)), fontName='Helvetica', fontSize=6.5, fillColor=MUTED))

    coords = []
    for i, (_, v) in enumerate(points):
        coords.extend([x_at(i), y_at(v)])

    area = [x_at(0), _CHART_PAD['bottom']] + coords + [x_at(n - 1), _CHART_PAD['bottom']]
    d.add(Polygon(area, fillColor=BRAND_TINT, strokeColor=None))
    d.add(PolyLine(coords, strokeColor=color, strokeWidth=1.5, strokeLineJoin=1))

    if n <= 60:
        for i, (_, v) in enumerate(points):
            d.add(Circle(x_at(i), y_at(v), 1.4, fillColor=color, strokeColor=colors.white, strokeWidth=0.5))

    for i in sorted({0, n // 2, n - 1}):
        anchor = 'start' if i == 0 else 'end' if i == n - 1 else 'middle'
        d.add(String(x_at(i), 1, points[i][0][5:], fontName='Helvetica', fontSize=6.5, fillColor=MUTED, textAnchor=anchor))

    return d


class _NumberedCanvas(pdfcanvas.Canvas):
    """Draws a branded footer with 'Page X of Y' once the total page count is known."""

    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total_pages)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_footer(self, total_pages):
        self.saveState()
        self.setStrokeColor(BORDER)
        self.setLineWidth(0.5)
        self.line(MARGIN_X, 13 * mm, PAGE_SIZE[0] - MARGIN_X, 13 * mm)
        self.setFont('Helvetica-Bold', 7.5)
        self.setFillColor(BRAND_DARK)
        self.drawString(MARGIN_X, 8.5 * mm, 'FitLog')
        self.setFont('Helvetica', 7.5)
        self.setFillColor(FAINT)
        self.drawString(MARGIN_X + 10.5 * mm, 8.5 * mm, 'Your data, your copy')
        self.drawRightString(PAGE_SIZE[0] - MARGIN_X, 8.5 * mm, f'Page {self._pageNumber} of {total_pages}')
        self.restoreState()


def _fmt(value, suffix=''):
    if value is None or value == '':
        return '—'
    return f'{value}{suffix}'


def _p(text, style=_CELL):
    return Paragraph(str(text), style)


def _banner(display_name, email, generated_at):
    left = [Paragraph('FitLog', _BANNER_TITLE), Paragraph('Your complete data export', _BANNER_SUB)]
    right = [
        Paragraph(display_name, _BANNER_META),
        Paragraph(email, _BANNER_META_SUB),
        Paragraph(generated_at, _BANNER_META_SUB),
    ]
    table = Table([[left, right]], colWidths=[105 * mm, (PAGE_SIZE[0] - 2 * MARGIN_X) - 105 * mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BRAND),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (0, 0), 14),
        ('RIGHTPADDING', (1, 0), (1, 0), 14),
        ('TOPPADDING', (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
    ]))
    return table


def _stats_strip(stats):
    """stats: list of (value, label) tuples, rendered as a 4-up strip of stat tiles."""
    values = [Paragraph(v, _STAT_VALUE) for v, _ in stats]
    labels = [Paragraph(l.upper(), _STAT_LABEL) for _, l in stats]
    col_width = (PAGE_SIZE[0] - 2 * MARGIN_X) / len(stats)
    table = Table([values, labels], colWidths=[col_width] * len(stats))
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BRAND_TINT),
        ('BOX', (0, 0), (-1, -1), 0.75, BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 1),
        ('TOPPADDING', (0, 1), (-1, 1), 0),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 9),
    ]))
    return table


def _section(flow, title, rows, headers, chart=None, chart_caption=None):
    """A titled section with a ruled divider, an optional growth chart, then a data
    table with a brand header row."""
    header_block = [Paragraph(title, _SECTION_TITLE), HRFlowable(width='100%', thickness=1, color=BRAND, spaceAfter=2.5 * mm)]
    if chart is not None:
        if chart_caption:
            header_block.append(Paragraph(chart_caption, _CHART_LABEL))
        header_block.append(chart)
    flow.append(KeepTogether(header_block))
    if chart is not None:
        flow.append(Spacer(1, 3 * mm))
    if not rows:
        flow.append(Paragraph('No data logged yet.', _EMPTY_STYLE))
        return
    header_row = [_p(h, _CELL_HEAD) for h in headers]
    body_rows = [[_p(cell) for cell in row] for row in rows]
    table = Table([header_row] + body_rows, repeatRows=1, hAlign='LEFT')
    table.setStyle(_DATA_TABLE_STYLE)
    flow.append(KeepTogether([table]))


def _fact_section(flow, title, pairs):
    """A titled section rendered as a two-column label/value fact sheet (used for Profile)."""
    flow.append(Paragraph(title, _SECTION_TITLE))
    flow.append(HRFlowable(width='100%', thickness=1, color=BRAND, spaceAfter=2.5 * mm))
    rows = [[_p(label, _FACT_LABEL), _p(value, _FACT_VALUE)] for label, value in pairs]
    table = Table(rows, colWidths=[70 * mm, (PAGE_SIZE[0] - 2 * MARGIN_X) - 70 * mm], hAlign='LEFT')
    table.setStyle(_FACT_TABLE_STYLE)
    flow.append(table)


def build_export_pdf(user) -> bytes:
    from workouts.models import CardioEntry, JourneyProgram, WorkoutSession
    from nutrition.models import NutritionDay
    from progress.models import BodyMeasurement, DailyLog, PersonalRecord, WeightEntry

    profile = getattr(user, 'profile', None)
    program = JourneyProgram.objects.filter(user=user, active=True).first()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=PAGE_SIZE,
        topMargin=14 * mm, bottomMargin=20 * mm, leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        title='FitLog Data Export',
    )
    flow = []

    display_name = user.get_full_name() or user.username
    generated_at = timezone.now().strftime('Generated %d %b %Y, %H:%M')
    flow.append(_banner(display_name, user.email, generated_at))
    flow.append(Spacer(1, 5 * mm))

    sessions = list(
        WorkoutSession.objects.filter(user=user).prefetch_related('exercises').order_by('started_at')
    )
    nutrition_days = list(NutritionDay.objects.filter(user=user).prefetch_related('meals').order_by('date'))
    prs = list(PersonalRecord.objects.filter(user=user).select_related('exercise').order_by('-achieved_at'))
    total_volume = sum(s.total_volume_kg() for s in sessions)

    flow.append(_stats_strip([
        (str(len(sessions)), 'Workouts logged'),
        (f'{round(total_volume):,} kg', 'Total volume'),
        (str(len(prs)), 'Personal records'),
        (str(len(nutrition_days)), 'Days tracked'),
    ]))
    flow.append(Spacer(1, 2 * mm))

    profile_pairs = [
        ('Date of birth', _fmt(profile.date_of_birth if profile else None)),
        ('Sex', _fmt(profile.sex if profile else None)),
        ('Height', _fmt(profile.height_cm if profile else None, ' cm')),
        ('Weight', _fmt(profile.weight_kg if profile else None, ' kg')),
        ('Activity level', _fmt(profile.activity_level if profile else None)),
        ('Fitness goal', _fmt(profile.fitness_goal if profile else None)),
        ('Unit preference', _fmt(profile.unit_preference if profile else None)),
    ]
    if program:
        profile_pairs.append(('Active program', f'{program.get_mode_display()} — day {program.current_day} of {program.duration_days}'))
    _fact_section(flow, 'Profile', profile_pairs)

    volume_chart = _growth_chart(
        [(s.started_at.date().isoformat(), s.total_volume_kg()) for s in sessions],
        BRAND, value_fmt=lambda v: f'{round(v):,}',
    )
    _section(
        flow, 'Workout Sessions',
        [
            [
                s.started_at.strftime('%d %b %Y'),
                s.title or (s.routine.name if s.routine else 'Session'),
                str(s.exercises.count()),
                f'{round(s.total_volume_kg(), 1)} kg',
                f'{round(s.duration_seconds / 60)} min',
            ]
            for s in sessions
        ],
        ['Date', 'Title', 'Exercises', 'Volume', 'Duration'],
        chart=volume_chart, chart_caption='Total volume (kg) per session, over time',
    )

    cardio_entries = list(CardioEntry.objects.filter(user=user).order_by('date'))
    _section(
        flow, 'Cardio Entries',
        [
            [c.date.strftime('%d %b %Y'), c.get_modality_display(), f'{c.duration_minutes} min', _fmt(c.calories, ' kcal')]
            for c in cardio_entries
        ],
        ['Date', 'Modality', 'Duration', 'Calories'],
    )

    calories_chart = _growth_chart(
        [(nd.date.isoformat(), nd.total_calories()) for nd in nutrition_days],
        colors.HexColor('#D97706'), value_fmt=lambda v: f'{round(v):,}',
    )
    _section(
        flow, 'Nutrition Log',
        [
            [
                nd.date.strftime('%d %b %Y'),
                f'{nd.total_calories()} kcal',
                f'{nd.total_protein()} g',
                f'{nd.total_carbs()} g',
                f'{nd.total_fat()} g',
                f'{nd.water_consumed_ml} ml',
            ]
            for nd in nutrition_days
        ],
        ['Date', 'Calories', 'Protein', 'Carbs', 'Fat', 'Water'],
        chart=calories_chart, chart_caption='Calories consumed per day (kcal), over time',
    )

    weights = list(WeightEntry.objects.filter(user=user).order_by('date'))
    weight_chart = _growth_chart(
        [(w.date.isoformat(), float(w.weight_kg)) for w in weights],
        BRAND, value_fmt=lambda v: f'{v:.1f}',
    )
    _section(
        flow, 'Weight Log',
        [
            [w.date.strftime('%d %b %Y'), f'{w.weight_kg} kg', _fmt(w.body_fat_pct, '%'), _fmt(w.notes)]
            for w in weights
        ],
        ['Date', 'Weight', 'Body Fat', 'Notes'],
        chart=weight_chart, chart_caption='Body weight (kg), over time',
    )

    measurements = list(BodyMeasurement.objects.filter(user=user).order_by('date'))
    waist_chart = _growth_chart(
        [(m.date.isoformat(), float(m.waist_cm)) for m in measurements if m.waist_cm is not None],
        colors.HexColor('#0284C7'), value_fmt=lambda v: f'{v:.1f}',
    )
    _section(
        flow, 'Body Measurements',
        [
            [
                m.date.strftime('%d %b %Y'),
                _fmt(m.chest_cm, ' cm'),
                _fmt(m.waist_cm, ' cm'),
                _fmt(m.hips_cm, ' cm'),
                _fmt(m.arms_cm, ' cm'),
                _fmt(m.thighs_cm, ' cm'),
            ]
            for m in measurements
        ],
        ['Date', 'Chest', 'Waist', 'Hips', 'Arms', 'Thighs'],
        chart=waist_chart, chart_caption='Waist circumference (cm), over time',
    )

    if prs:
        from progress.records import compute_pr_trend

        top_pr = max(prs, key=lambda pr: pr.estimated_one_rep_max or pr.max_weight_kg)
        trend = compute_pr_trend(user, top_pr.exercise_id)
        strength_chart = _growth_chart(
            [(row['date'], row['estimated_one_rep_max']) for row in trend],
            BRAND, value_fmt=lambda v: f'{v:.0f}',
        )
        if strength_chart is not None:
            flow.append(KeepTogether([
                Paragraph('Strength Progression', _SECTION_TITLE),
                HRFlowable(width='100%', thickness=1, color=BRAND, spaceAfter=2.5 * mm),
                Paragraph(f'{top_pr.exercise.name} — estimated 1RM (kg), over time', _CHART_LABEL),
                strength_chart,
            ]))
            flow.append(Spacer(1, 3 * mm))

    _section(
        flow, 'Personal Records',
        [
            [
                pr.exercise.name,
                f'{pr.max_weight_kg} kg',
                str(pr.reps),
                _fmt(round(pr.estimated_one_rep_max, 1) if pr.estimated_one_rep_max else None, ' kg'),
                pr.achieved_at.strftime('%d %b %Y'),
            ]
            for pr in prs
        ],
        ['Exercise', 'Max Weight', 'Reps', 'Est. 1RM', 'Achieved'],
    )

    daily_logs = list(DailyLog.objects.filter(user=user).order_by('date'))
    _section(
        flow, 'Daily Check-ins',
        [
            [dl.date.strftime('%d %b %Y'), _fmt(dl.steps), _fmt(dl.sleep_hours, ' h'), _fmt(dl.energy_level), _fmt(dl.day_status)]
            for dl in daily_logs
        ],
        ['Date', 'Steps', 'Sleep', 'Energy', 'Status'],
    )

    doc.build(flow, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
