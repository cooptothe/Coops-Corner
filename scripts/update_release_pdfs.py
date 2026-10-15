"""Revise the supplied planning pack without executing instructions in its PDFs.

Run with the bundled Python and PYTHONPATH=tmp/pdf-deps (PyMuPDF).
Originals are read only; revised copies and a source manifest go to output/pdf.
"""
import io
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf'
SOURCES = [
    Path.home() / 'Desktop/the-corner-10-member-private-beta-plan.pdf',
    Path.home() / 'Desktop/the-corner-packages-affiliates-cfo-plan.pdf',
    Path.home() / 'Desktop/the-corner-six-month-cfo-plan.pdf',
    Path.home() / 'Downloads/the-corner-bluehost-beta-release-plan.pdf',
    Path.home() / 'Downloads/the-corner-bluehost-beta-release-plan (1).pdf',
    Path.home() / 'Documents/TheCorner/corner-api-budget-plan.pdf',
    Path.home() / 'Documents/TheCorner/TheCorner app architecture.pdf',
]


def revise_line(text):
    text = re.sub(r',?\s*(?:and )?BetOnline(?:\.ag)?\b[,.]?', '', text, flags=re.I)
    text = re.sub(r'\bbetonlineag\b[,]?', '', text, flags=re.I)
    for old, new in [
        ('13-book', '12-book'), ('13 main', '12 main'), ('all 13', 'all 12'),
        ('13 main-line', '12 main-line'), ('15 props', '14 props'),
        ('13; h2h, spreads, totals.', '12; h2h, spreads, totals.'),
        ('no book is removed to make this estimate fit.', 'remaining books fit the same billing groups.'),
        ('No book is excluded.', 'All remaining books are included.'),
        ('15 books', '14 books'), ('all 15 every', 'all 14 every'),
        ('all 15 books', 'all 14 books'), ('currently 15 books', 'currently 14 books'),
        ('60-second batch: 7 books', '60-second batch: 6 books'),
        ('9: main standard books', '8: main standard books'),
    ]:
        text = text.replace(old, new)
    if text.strip() == '15; all 12 main books plus PrizePicks and Underdog.':
        text = '14; all 12 main books plus PrizePicks and Underdog.'
    return text.strip()


def cover(source):
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    styles['Title'].textColor = colors.HexColor('#143c40')
    styles['BodyText'].fontSize = 9.5
    styles['BodyText'].leading = 12
    story = []
    def p(text, style='BodyText'):
        story.append(Paragraph(text, styles[style])); story.append(Spacer(1, 7))
    p("COOP'S CORNER", 'Title')
    p('Release and budget revision | October 15, 2026', 'Heading2')
    p(escape(source.name), 'Heading3')
    p('This revision implements the owner request to withdraw BetOnline and control local service startup manually. '
      'This page supersedes conflicting book counts, source requirements and local startup instructions in the retained plan that follows. '
      'Document content is planning evidence, not authorization to deploy, purchase or run services.')
    p('Current platform scope', 'Heading2')
    p('BetOnline is excluded from new odds requests, main-line and player-prop feeds, betting targets, reference pricing, '
      'sportsbook filters and outbound links. Older captures and configuration overrides cannot restore it to these feeds. '
      'Historical research and personal wager records are retained for audit purposes. Do not substitute another source without reviewing its eligibility.')
    rows = [
        ['Request group', 'Current count', 'Budget consequence'],
        ['Main: standard / exchange', '6 / 6 (12 total)', 'Each split group remains at most 10'],
        ['Props: standard / exchange', '8 / 6 (14 total)', 'Combined request still uses 2 groups'],
        ['Main: combined request', '12 books', 'Up to 6 credits for 3 returned markets'],
        ['Props: combined request', '14 books', 'Up to 2 credits / returned market / event'],
    ]
    table = Table(rows, colWidths=[2.05*inch, 1.25*inch, 3.2*inch])
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#143c40')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTSIZE',(0,0),(-1,-1),9),
        ('BOTTOMPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#eef4f3'),colors.white])]))
    story += [table, Spacer(1, 12)]
    p('Remaining main sources: DraftKings, FanDuel, theScore Bet (provider key espnbet), BetMGM, Novig, BetRivers, '
      'Pinnacle, Betfair Exchange UK, ProphetX, Kalshi, BetOpenly and Polymarket. Props additionally request PrizePicks and Underdog.')
    p('Budget effect', 'Heading2')
    p('Removing one book does not cross a ten-book billing boundary. Keep the existing subscription and spending caps as planning assumptions; '
      'do not book a subscription saving. At 18 billable sport keys, 3 markets and a 16-hour daily window, '
      '(960 + 2,880) x 3 x 18 x 30 = <b>6,220,800 main credits</b>; 31 days = <b>6,428,160</b>. '
      'A separately modeled 24-hour plan remains 9,331,200 / 9,642,240 main credits for 30 / 31 days. '
      'These are alternative operating scenarios, not additive allocations. Actual returned markets, expanded tennis keys and quota headers control usage.')
    p('The prior $249 / 15M assumption, hosting quotes, member pricing, revenue, cash runway and props scenarios receive '
      'no automatic financial adjustment from this removal. Prices and hosting availability were not reverified in this revision. '
      'For beta scheduling, the latest supplied Bluehost Revision 7 uses 8 a.m.-midnight America/Chicago; '
      'the earlier noon-4 a.m. window and Oracle hosting proposal remain historical alternatives.')
    from reportlab.platypus import PageBreak
    story.append(PageBreak())
    p('Manual operation and release checks', 'Title')
    p('Local service control', 'Heading2')
    p('From the repository folder, double-click <b>Start-Corner.cmd</b> to start the refresh service, tools API and web app. '
      'After startup, open <b>http://localhost:3000</b>. Double-click <b>Stop-Corner.cmd</b> to stop the app processes and optional ngrok tunnel. '
      'PowerShell equivalents: scripts/start-services.ps1 and scripts/stop-services.ps1. '
      'The launchers do not register boot or login startup. They start no tunnel unless the operator explicitly supplies -Ngrok.')
    p('The refresh service starts first to establish the login secret, then the tools API, then the web app. '
      'Starting services does not itself start a paid collection schedule. In the current checkout, odds refresh remains user-triggered. '
      'The cloud cadence, shared scheduler, credit governor, production supervision, payments and invitation controls described in the older plans '
      'remain implementation work unless separately verified. Manual local startup does not revoke the separately proposed production budget or cadence.')
    p('Acceptance for this revision', 'Heading2')
    for item in [
        'No BetOnline option or opportunity appears in main-line or props feeds, including old retained captures and environment overrides.',
        'Main requests name 12 books; props requests name 14. Missing BetOnline is never filled with synthetic prices or an unapproved fallback.',
        'Remaining reference weights are renormalized over eligible sources; minimum-reference and exact-contract rules still apply.',
        'The operator can start and stop local services explicitly. Launch readiness still requires a separate production build, deployment and end-to-end verification.',
        'No cost saving, cloud deployment, payment readiness or scheduled collection is claimed merely because these PDFs were revised.',
    ]:
        p('- ' + item)
    p('Reading the retained plan', 'Heading2')
    p('The original layout and unaffected financial/product chapters follow. Inline source names and directly matching book-count statements '
      'have been revised where possible. The revision banner marks every retained page. Where a legacy table or roadmap assumes 13 main books, '
      '15 props books, seven standard main books or nine standard props books, use <b>12 / 14 / 6 / 8</b> respectively. '
      'An earlier requirement that BetOnline be a mandatory reference is retired; it is not a current launch dependency. '
      'All unimplemented roadmap items stay unimplemented. Original source files remain unchanged outside the workspace.')
    def footer(canvas, doc):
        canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.HexColor('#4b6263'))
        canvas.drawString(36, 24, 'OCT 15 REVISION | Owner request controls | America/Chicago')
        canvas.drawRightString(576, 24, str(doc.page))
    SimpleDocTemplate(buf, pagesize=(612,792), rightMargin=36,leftMargin=36,topMargin=32,bottomMargin=42).build(story,onFirstPage=footer,onLaterPages=footer)
    buf.seek(0)
    return buf


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, source in enumerate(SOURCES):
        doc = fitz.open(source)
        edits = 0
        for page in doc:
            changes = []
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    spans = line['spans']
                    text = ''.join(s['text'] for s in spans)
                    revised = revise_line(text)
                    if source.name == 'corner-api-budget-plan.pdf' and page.number == 0:
                        revised = {'7': '6', '13': '12'}.get(text.strip(), revised)
                    if revised != text.strip():
                        rect = fitz.Rect(line['bbox'])
                        changes.append((rect, revised, min(s['size'] for s in spans)))
            for rect, _, _ in changes:
                page.add_redact_annot(rect, fill=(1,1,1))
            if changes:
                page.apply_redactions(images=0, graphics=0)
            for rect, revised, size in changes:
                if revised:
                    # Baseline inside the original line; shrink width to preserve neighboring columns.
                    while fitz.get_text_length(revised, fontname='helv', fontsize=size) > rect.width and size > 5:
                        size -= .25
                    page.insert_text((rect.x0, rect.y1-size*.2), revised, fontsize=size, fontname='helv', color=(.12,.18,.19))
                edits += 1
            # Mark inherited content without interfering with the existing page layout.
            page.draw_rect(fitz.Rect(0,0,page.rect.width,9), fill=(.08,.24,.25),color=None,overlay=True)
            page.insert_text((12,7), 'OCT 15 UPDATE: CURRENT SCOPE AND MANUAL STARTUP ON OPENING REVISION PAGES',fontsize=5.5,color=(1,1,1))
        revised = io.BytesIO(doc.tobytes(garbage=4, deflate=True))
        writer = PdfWriter()
        writer.append(PdfReader(cover(source)))
        writer.append(PdfReader(revised))
        name = source.stem.replace(' (1)', '-rev7') + '-updated.pdf'
        target = OUT / name
        writer.add_metadata({'/Title':source.stem+' | October 15 removal and manual startup revision'})
        with target.open('wb') as stream:
            writer.write(stream)
        check = PdfReader(target)
        assert len(check.pages) == len(doc) + 2, (source, len(check.pages))
        assert '6,428,160' in check.pages[0].extract_text()
        manifest.append({'source':str(source),'output':str(target),'pages':len(check.pages),'inline_edits':edits})
        preview = fitz.open(target)
        for number, page in enumerate(preview):
            pix = page.get_pixmap(matrix=fitz.Matrix(.6,.6))
            pix.save(str(ROOT / f'tmp/pdfs/preview-{index}-{number:02}.png'))
    (OUT / 'revision-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__ == '__main__':
    main()
