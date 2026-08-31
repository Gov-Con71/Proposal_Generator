import type { Metadata } from 'next'
import Link from 'next/link'
import {
  ShieldCheck, Check, ArrowRight, AlertCircle, ChevronDown,
  Building2, Search, Clock, Download, Users, ListChecks,
} from 'lucide-react'

/** Public marketing landing page.
 *
 *  Deliberately a Server Component with no client boundary: the whole point is
 *  that a crawler receives the copy in the initial HTML. The only interactive
 *  element is the FAQ, built on <details>/<summary> so it needs no JavaScript
 *  and stays keyboard-accessible for free. */

export const metadata: Metadata = {
  title: 'ProposalAI | RFP Compliance Matrix & Proposal Automation',
  description:
    'Turn any federal RFP into a compliance matrix in minutes. ProposalAI shreds solicitations, drafts cited sections, and exports submission-ready volumes.',
  // The root layout sets robots noindex for the whole application, which is
  // right for an authenticated product and wrong for the one page meant to be
  // found. Overridden here only.
  robots: { index: true, follow: true },
  openGraph: {
    title: 'ProposalAI | RFP Compliance Matrix & Proposal Automation',
    description:
      'Turn any federal RFP into a compliance matrix in minutes, with a source quote behind every extracted fact.',
    type: 'website',
  },
}

const CAPABILITIES = [
  {
    icon: Building2,
    title: 'Company profile',
    body: 'CAGE, UEI, NAICS, CMMC level, clearances, socio-economic status and rates — entered once, cited everywhere.',
  },
  {
    icon: Search,
    title: 'Past performance library',
    body: 'Searchable contract history that grounds capability claims in work you actually did.',
  },
  {
    icon: Clock,
    title: 'Live processing',
    body: 'Watch parse, extract and classify as they run — no silent queue, no guessing.',
  },
  {
    icon: Download,
    title: 'Volume exports',
    body: 'PDF, DOCX, XLSX and ZIP — volume by volume, in the structure Section L asked for.',
  },
  {
    icon: Users,
    title: 'Roles and tenancy',
    body: 'Admin, analyst and viewer, with every company’s data isolated from every other.',
  },
  {
    icon: ListChecks,
    title: 'Compliance tracking',
    body: 'Move every requirement from missing to addressed, with an owner and a section behind each one.',
  },
]

const FAQS = [
  {
    q: 'How does ProposalAI prevent AI hallucination in a proposal?',
    a: 'Drafts are checked against the evidence they were given. Any contract number or dollar figure that doesn’t appear in your company profile or past performance library blocks the save, along with unfilled placeholders and untagged requirements. The section is held for review rather than shipped with an invented fact in it.',
  },
  {
    q: 'What file formats can I upload?',
    a: 'PDF, DOCX and TXT, up to 50MB per document — for both solicitations and past performance evidence. Scanned documents need OCR first, since there is no text to extract from an image.',
  },
  {
    q: 'Can I edit the requirements it extracted?',
    a: 'Yes. Every row in the compliance matrix is editable — text, section number, category and status. The extraction is a starting point you correct, not a black box you accept.',
  },
  {
    q: 'Does it handle DoD solicitations and CUI?',
    a: 'It reads DoD solicitations, including Sections L and M, and captures clearance and CMMC requirements as first-class rows. Handling CUI is a deployment decision — the platform runs in your own environment, so the controls are yours to set.',
  },
  {
    q: 'What can I export, and in what structure?',
    a: 'PDF, DOCX, XLSX and ZIP. The outline mirrors the volumes Section L requires, using the government’s own names and order, so what you export matches what the solicitation asked for.',
  },
]

const MATRIX_ROWS = [
  { section: 'C.2.1', text: 'The Contractor shall design, develop, and deploy a modernized logistics data ingestion pipeline…', category: 'Technical', tone: 'bg-primary-50 text-primary-800', status: 'Addressed', dot: 'bg-success-400' },
  { section: 'C.2.2', text: '…migrate all legacy applications to an approved Impact Level 5 (IL5) cloud environment…', category: 'Technical', tone: 'bg-primary-50 text-primary-800', status: 'Addressed', dot: 'bg-success-400' },
  { section: 'H.1', text: 'All Contractor personnel shall possess and maintain an active SECRET security clearance…', category: 'Security', tone: 'bg-warning-50 text-warning-800', status: 'Addressed', dot: 'bg-success-400' },
  { section: 'L.2.2', text: 'Volume I, Technical Approach, shall not exceed thirty (30) pages, excluding resumes…', category: 'Instruction', tone: 'bg-neutral-50 text-neutral-600', status: 'Partial', dot: 'bg-warning-400' },
  { section: 'L.3.1', text: '…a minimum of three (3) and a maximum of five (5) past performance references…', category: 'Past Perf.', tone: 'bg-success-50 text-success-800', status: 'Missing', dot: 'bg-danger-400' },
  { section: 'M.2', text: 'Factor 1, Technical Approach, is significantly more important than Factor 2…', category: 'Evaluation', tone: 'bg-neutral-50 text-neutral-600', status: 'Addressed', dot: 'bg-success-400' },
]

function Eyebrow({ children, tone = 'text-primary-600' }: { children: React.ReactNode; tone?: string }) {
  return (
    <span className={`font-mono text-[11px] uppercase tracking-[0.14em] ${tone}`}>{children}</span>
  )
}

export default function LandingPage() {
  return (
    <div className="bg-white text-neutral-900 font-sans">
      {/* ── Nav ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 flex h-[72px] items-center justify-between border-b border-neutral-100 bg-white/95 px-6 backdrop-blur lg:px-[120px]">
        <Link href="/" className="flex items-center gap-2.5">
          <ShieldCheck className="h-6 w-6 text-primary-600" strokeWidth={1.5} />
          <span className="text-base font-semibold tracking-tight">ProposalAI</span>
        </Link>
        <nav className="flex items-center gap-4 sm:gap-8">
          <a href="#how-it-works" className="hidden text-sm text-neutral-600 hover:text-neutral-900 md:block">How it works</a>
          <a href="#capabilities" className="hidden text-sm text-neutral-600 hover:text-neutral-900 md:block">Capabilities</a>
          <a href="#faq" className="hidden text-sm text-neutral-600 hover:text-neutral-900 md:block">FAQ</a>
          {/* Touch targets stay ≥44px until the pointer is a mouse. Both of
              these sat at ~36px and text-height respectively, which is under
              the threshold on exactly the devices that can least afford a
              mis-tap. */}
          <Link
            href="/login"
            className="flex h-12 items-center px-1 text-sm text-neutral-600 hover:text-neutral-900 sm:h-auto sm:px-0"
          >
            Sign in
          </Link>
          <Link
            href="/proposals/new"
            className="flex h-12 items-center rounded-md bg-primary-600 px-4 text-sm font-medium text-white transition-colors hover:bg-primary-800 sm:h-9"
          >
            Upload an RFP
          </Link>
        </nav>
      </header>

      {/* ── 1 · Hero ────────────────────────────────────────────────────── */}
      <section className="overflow-hidden border-b border-neutral-100 bg-neutral-50 px-6 py-16 lg:py-[88px] lg:pl-[120px] lg:pr-0">
        <div className="flex flex-col items-start gap-12 lg:flex-row lg:items-center lg:gap-16">
          <div className="flex w-full max-w-[560px] shrink-0 flex-col gap-7">
            <div className="flex items-center gap-2">
              <span className="h-px w-6 bg-primary-600" />
              <Eyebrow>Federal proposal automation</Eyebrow>
            </div>

            <h1 className="font-display text-[34px] font-medium leading-[1.1] tracking-tight sm:text-5xl lg:text-[56px]">
              Every requirement. Every citation. Every time.
            </h1>

            <p className="max-w-[500px] text-[17px] leading-relaxed text-neutral-600 text-pretty">
              ProposalAI reads your solicitation the way a contracting officer does — then builds
              the compliance matrix and drafts the response, with a source quote behind every fact.
            </p>

            <div className="flex flex-col gap-3 pt-1 sm:flex-row sm:items-center">
              <Link
                href="/proposals/new"
                className="flex h-12 items-center justify-center rounded-md bg-primary-600 px-7 text-[15px] font-medium text-white transition-colors hover:bg-primary-800"
              >
                Upload an RFP
              </Link>
              <Link
                href="/login"
                className="flex h-12 items-center justify-center rounded-md border border-primary-100 px-6 text-[15px] font-medium text-primary-600 transition-colors hover:bg-primary-50"
              >
                See a sample matrix
              </Link>
            </div>

            <div className="flex items-center gap-2 pt-1">
              <Check className="h-4 w-4 shrink-0 text-success-400" strokeWidth={2.5} />
              <span className="text-[13px] text-neutral-400">
                PDF, DOCX or TXT up to 50MB · No template required
              </span>
            </div>
          </div>

          {/* The compliance matrix is the hero image: the actual artifact the
              product makes. Cropped at the right edge on desktop to imply more
              rows than fit; scrolls inside itself on narrow screens so the page
              body never scrolls sideways. */}
          <div className="w-full min-w-0 lg:w-[820px] lg:shrink-0">
            <div className="overflow-x-auto rounded-lg border border-neutral-100 bg-white shadow-[0_12px_32px_rgba(44,44,42,0.10)]">
              <div className="min-w-[680px]">
                <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3.5">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-sm font-semibold">Compliance Matrix</span>
                    <span className="font-mono text-[11px] text-neutral-400">
                      W15QKN-26-R-0117 · 45 requirements
                    </span>
                  </div>
                  <div className="hidden gap-1.5 sm:flex">
                    <span className="rounded bg-primary-50 px-2.5 py-1 text-[11px] font-medium text-primary-800">All 45</span>
                    <span className="rounded bg-neutral-50 px-2.5 py-1 text-[11px] text-neutral-600">Addressed 31</span>
                    <span className="rounded bg-neutral-50 px-2.5 py-1 text-[11px] text-neutral-600">Missing 6</span>
                  </div>
                </div>

                <div className="grid grid-cols-[86px_1fr_132px_116px] border-b border-neutral-100 bg-neutral-50 px-5 py-2.5">
                  {['Section', 'Requirement', 'Category', 'Status'].map((h) => (
                    <span key={h} className="text-[10px] uppercase tracking-wider text-neutral-400">{h}</span>
                  ))}
                </div>

                {MATRIX_ROWS.map((r) => (
                  <div
                    key={r.section}
                    className="grid grid-cols-[86px_1fr_132px_116px] items-center border-b border-neutral-100 px-5 py-3 last:border-0"
                  >
                    <span className="font-mono text-xs text-primary-600">{r.section}</span>
                    <span className="pr-4 text-[13px] text-neutral-800">{r.text}</span>
                    <div><span className={`rounded px-2.5 py-1 text-[11px] ${r.tone}`}>{r.category}</span></div>
                    <div className="flex items-center gap-2">
                      <span className={`h-[7px] w-[7px] rounded-full ${r.dot}`} />
                      <span className="text-xs text-neutral-600">{r.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 2 · The shred ───────────────────────────────────────────────── */}
      <section id="how-it-works" className="scroll-mt-20 bg-neutral-100 px-6 py-20 lg:px-[120px] lg:py-[104px]">
        <div className="mx-auto flex max-w-[720px] flex-col items-center gap-4 text-center">
          <h2 className="font-display text-3xl font-medium leading-tight tracking-tight lg:text-[40px]">
            From solicitation to compliance matrix in minutes
          </h2>
          <p className="text-[17px] leading-relaxed text-neutral-600 text-pretty">
            Every “shall” statement, pulled with its section number and verbatim text, then
            classified — Technical, Security, Past Performance, Instruction, Evaluation Criteria.
          </p>
        </div>

        <div className="mt-14 flex flex-col items-stretch gap-6 lg:flex-row">
          <article className="flex flex-1 flex-col gap-3.5 rounded-lg border border-neutral-200 bg-white p-6">
            <Eyebrow tone="text-neutral-400">01 · The solicitation</Eyebrow>
            <div className="flex flex-col gap-2 pt-1">
              <span className="h-1.5 w-[78%] rounded-sm bg-neutral-100" />
              <span className="h-1.5 w-[92%] rounded-sm bg-neutral-100" />
              <div className="rounded-sm border-l-2 border-warning-400 bg-warning-50 px-3 py-2.5">
                <span className="text-xs leading-relaxed text-neutral-800">
                  The Contractor shall provide system availability of not less than 99.5% measured monthly.
                </span>
              </div>
              <span className="h-1.5 w-[85%] rounded-sm bg-neutral-100" />
              <span className="h-1.5 w-[64%] rounded-sm bg-neutral-100" />
            </div>
          </article>

          <div className="flex items-center justify-center text-neutral-400">
            <ArrowRight className="h-5 w-5 rotate-90 lg:rotate-0" strokeWidth={1.25} />
          </div>

          <article className="flex flex-1 flex-col gap-3.5 rounded-lg border border-neutral-200 bg-white p-6">
            <Eyebrow tone="text-neutral-400">02 · Extracted</Eyebrow>
            <div className="flex flex-col gap-3 pt-1">
              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-neutral-400">Section</span>
                <span className="font-mono text-sm text-primary-600">C.2.4</span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-neutral-400">Verbatim text</span>
                <span className="text-xs leading-relaxed text-neutral-800">
                  The Contractor shall provide system availability of not less than 99.5% measured monthly.
                </span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-neutral-400">Category</span>
                <div><span className="rounded bg-primary-50 px-2.5 py-1 text-[11px] text-primary-800">Technical</span></div>
              </div>
            </div>
          </article>

          <div className="flex items-center justify-center text-neutral-400">
            <ArrowRight className="h-5 w-5 rotate-90 lg:rotate-0" strokeWidth={1.25} />
          </div>

          <article className="flex flex-1 flex-col gap-3.5 rounded-lg border border-neutral-200 bg-white p-6">
            <Eyebrow tone="text-neutral-400">03 · In the matrix</Eyebrow>
            <div className="mt-1 overflow-hidden rounded-md border border-neutral-100">
              <div className="flex items-center gap-2.5 border-b border-neutral-100 bg-neutral-50 px-3 py-2.5">
                <span className="font-mono text-[11px] text-neutral-400">#12</span>
                <span className="text-[11px] text-neutral-400">of 45</span>
              </div>
              <div className="flex flex-col gap-2.5 p-3">
                <span className="font-mono text-[13px] text-primary-600">C.2.4</span>
                <span className="text-xs leading-relaxed text-neutral-800">
                  System availability ≥ 99.5%, measured monthly.
                </span>
                <div className="flex items-center gap-2">
                  <span className="h-[7px] w-[7px] rounded-full bg-success-400" />
                  <span className="text-xs text-neutral-600">Addressed · § 3.2 Availability</span>
                </div>
              </div>
            </div>
          </article>
        </div>
      </section>

      {/* ── 3 · Citation ────────────────────────────────────────────────── */}
      <section className="flex flex-col items-center gap-12 bg-white px-6 py-20 lg:flex-row lg:gap-20 lg:px-[120px] lg:py-[104px]">
        <div className="flex flex-1 flex-col gap-5">
          <Eyebrow>Traceable extraction</Eyebrow>
          <h2 className="font-display text-3xl font-medium leading-tight tracking-tight lg:text-[40px]">
            It reads Sections L and M, not just the SOW
          </h2>
          <p className="text-[17px] leading-relaxed text-neutral-600 text-pretty">
            Solicitation number, agency, NAICS, set-aside, deadlines, page limits, required volumes,
            evaluation factors — captured as structured fields, each carrying the exact sentence it
            came from.
          </p>
          <p className="text-[15px] leading-relaxed text-neutral-400 text-pretty">
            A proposal whose structure doesn’t mirror Section L is non-responsive. So the outline is
            built from the government’s own volume names, in the government’s own order.
          </p>
        </div>

        <div className="w-full overflow-hidden rounded-lg border border-neutral-100 bg-neutral-50 lg:w-[560px] lg:shrink-0">
          <dl className="flex flex-col gap-4 px-6 py-6">
            {[
              ['Solicitation number', 'W15QKN-26-R-0117', true],
              ['NAICS code', '541512', true],
              ['Set-aside', 'Total Small Business', false],
              ['Proposals due', '26 March 2026, 4:00 PM ET', false],
            ].map(([label, value, mono], i, arr) => (
              <div key={label as string}>
                <div className="flex items-baseline justify-between gap-4">
                  <dt className="text-[13px] text-neutral-400">{label as string}</dt>
                  <dd className={`text-sm ${mono ? 'font-mono' : ''}`}>{value as string}</dd>
                </div>
                {i < arr.length - 1 && <div className="mt-4 h-px bg-neutral-100" />}
              </div>
            ))}
          </dl>

          <div className="flex flex-col gap-2.5 border-t border-neutral-100 bg-white px-6 py-5">
            <Eyebrow tone="text-neutral-400">Source quote</Eyebrow>
            <blockquote className="border-l-2 border-primary-600 py-0.5 pl-4">
              <span className="font-mono text-[13px] leading-loose text-neutral-800">
                “NAICS Code: 541512 — Computer Systems Design Services”
              </span>
            </blockquote>
            <span className="text-xs text-neutral-400">
              Verified against the source document. Unmatched citations are dropped, not shown.
            </span>
          </div>
        </div>
      </section>

      {/* ── 4 · Traceability ────────────────────────────────────────────── */}
      <section className="flex flex-col-reverse items-center gap-12 border-y border-neutral-100 bg-neutral-50 px-6 py-20 lg:flex-row lg:gap-20 lg:px-[120px] lg:py-[104px]">
        <div className="w-full rounded-lg border border-neutral-100 bg-white p-7 lg:w-[620px] lg:shrink-0">
          <div className="mb-4 flex items-center justify-between">
            <span className="text-sm font-semibold">Technical Approach</span>
            <span className="rounded bg-warning-50 px-2.5 py-1 text-[11px] text-warning-800">Needs review</span>
          </div>
          <p className="text-sm leading-[1.85] text-neutral-800 text-pretty">
            Our approach delivers a modernized logistics data ingestion pipeline sized for a minimum
            of 2,000,000 transaction records per twenty-four hour period, with horizontal scaling
            verified under peak load.{' '}
            <span className="rounded-sm bg-primary-50 px-1.5 py-0.5 font-mono text-xs text-primary-800">[Req 1]</span>{' '}
            Migration to the approved IL5 environment proceeds in four cutover windows, holding
            cumulative scheduled downtime below seventy-two hours.{' '}
            <span className="rounded-sm bg-primary-50 px-1.5 py-0.5 font-mono text-xs text-primary-800">[Req 2]</span>{' '}
            All externally consumed services conform to OpenAPI 3.1.{' '}
            <span className="rounded-sm bg-primary-50 px-1.5 py-0.5 font-mono text-xs text-primary-800">[Req 3]</span>
          </p>
          <div className="mt-4 flex items-center gap-2">
            <Check className="h-4 w-4 text-success-400" strokeWidth={2.5} />
            <span className="text-xs text-neutral-600">7 of 7 requirements tagged</span>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-5">
          <Eyebrow>Requirement-level traceability</Eyebrow>
          <h2 className="font-display text-3xl font-medium leading-tight tracking-tight lg:text-[40px]">
            Drafts that cite their sources
          </h2>
          <p className="text-[17px] leading-relaxed text-neutral-600 text-pretty">
            Every section is grounded in your company profile and past performance library, then
            reviewed by a compliance critic for coverage, alignment to the evaluation criteria, and
            unsupported claims — and sent back for revision until it holds up.
          </p>
          <p className="text-[15px] leading-relaxed text-neutral-400 text-pretty">
            Inline tags let a reviewer see exactly which sentence answers which clause, without
            re-reading the solicitation beside the draft.
          </p>
        </div>
      </section>

      {/* ── 5 · The refusal ─────────────────────────────────────────────── */}
      <section className="flex flex-col items-center gap-12 bg-white px-6 py-20 lg:px-[120px] lg:py-[104px]">
        <div className="flex max-w-[760px] flex-col items-center gap-4 text-center">
          <Eyebrow tone="text-danger-600">Guardrails</Eyebrow>
          <h2 className="font-display text-[32px] font-medium leading-[1.12] tracking-tight lg:text-[44px]">
            It would rather leave a gap than invent a number
          </h2>
          <p className="text-[17px] leading-relaxed text-neutral-600 text-pretty">
            If a draft cites a contract number or dollar figure that appears nowhere in your
            evidence, ProposalAI won’t save it. In a compliance document, a confident fabrication is
            worse than a blank page.
          </p>
        </div>

        <div className="w-full max-w-[860px] overflow-hidden rounded-lg border border-l-[3px] border-neutral-100 border-l-danger-400 bg-white shadow-[0_8px_24px_rgba(44,44,42,0.07)]">
          <div className="flex items-center justify-between border-b border-neutral-100 px-6 py-4">
            <span className="text-sm font-semibold">Past Performance</span>
            <span className="rounded bg-danger-50 px-2.5 py-1 text-[11px] text-danger-800">Not saved</span>
          </div>
          <div className="px-6 py-5">
            <p className="text-sm leading-[1.85] text-neutral-400 text-pretty">
              Our team has delivered comparable modernization efforts valued at{' '}
              <span className="text-danger-600 line-through decoration-danger-400">$10.4M</span>,{' '}
              <span className="text-danger-600 line-through decoration-danger-400">$15.2M</span> and{' '}
              <span className="text-danger-600 line-through decoration-danger-400">$18.7M</span>{' '}
              across three federal agencies over the last five years.
            </p>
          </div>
          <div className="flex items-start gap-3 border-t border-danger-100 bg-danger-50 px-6 py-4">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger-600" strokeWidth={1.75} />
            <div className="flex flex-col gap-1">
              <span className="text-[13px] font-medium text-danger-800">Refused — unverifiable figures</span>
              <span className="font-mono text-xs leading-relaxed text-danger-600">
                cites dollar figures that appear nowhere in the supplied context — refusing to save
                as a likely hallucination
              </span>
            </div>
          </div>
        </div>

        <p className="text-center text-sm text-neutral-400">
          The same check rejects unfilled placeholders, superlative padding, and any requirement left untagged.
        </p>
      </section>

      {/* ── 6 · Capabilities ────────────────────────────────────────────── */}
      <section id="capabilities" className="scroll-mt-20 border-t border-neutral-100 bg-neutral-50 px-6 py-20 lg:px-[120px] lg:py-[104px]">
        <div className="flex max-w-[640px] flex-col gap-3.5">
          <h2 className="font-display text-3xl font-medium leading-tight tracking-tight lg:text-[40px]">
            Built for how GovCon teams actually work
          </h2>
          <p className="text-[17px] leading-relaxed text-neutral-600 text-pretty">
            The parts of a bid that never change, stored once and applied to every proposal.
          </p>
        </div>

        <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map(({ icon: Icon, title, body }) => (
            <article key={title} className="flex flex-col gap-3 rounded-lg border border-neutral-100 bg-white p-6">
              <Icon className="h-5 w-5 text-primary-600" strokeWidth={1.5} />
              <h3 className="text-base font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-neutral-600">{body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ── 7 · Who it's for ────────────────────────────────────────────── */}
      <section className="flex flex-col items-center gap-4 bg-primary-900 px-6 py-16 lg:px-[120px]">
        <Eyebrow tone="text-primary-200">Who it’s for</Eyebrow>
        <p className="max-w-[880px] text-center font-display text-xl leading-relaxed text-neutral-50 text-pretty lg:text-2xl">
          Small and mid-sized federal contractors, 8(a) and SDVOSB firms, and the capture and
          proposal managers answering RFPs, RFQs and SOWs from DoD, GSA and civilian agencies.
        </p>
      </section>

      {/* ── 8 · FAQ ─────────────────────────────────────────────────────── */}
      <section id="faq" className="scroll-mt-20 flex flex-col items-center gap-11 bg-white px-6 py-20 lg:px-[120px] lg:py-[104px]">
        <h2 className="text-center font-display text-3xl font-medium leading-tight tracking-tight lg:text-[40px]">
          Questions worth asking
        </h2>

        <div className="w-full max-w-[760px]">
          {FAQS.map(({ q, a }, i) => (
            <details key={q} open={i === 0} className="group border-b border-neutral-100 last:border-0">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-5 py-6 text-[17px] font-medium marker:hidden">
                {q}
                <ChevronDown
                  className="h-4 w-4 shrink-0 text-neutral-400 transition-transform group-open:rotate-180"
                  strokeWidth={1.75}
                />
              </summary>
              <p className="max-w-[660px] pb-6 text-[15px] leading-relaxed text-neutral-600 text-pretty">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* ── 9 · Closing CTA ─────────────────────────────────────────────── */}
      <section className="flex flex-col items-center gap-6 border-t border-neutral-100 bg-neutral-50 px-6 py-20 lg:py-24">
        <h2 className="max-w-[720px] text-center font-display text-[32px] font-medium leading-[1.12] tracking-tight lg:text-[44px]">
          Stop building the matrix by hand
        </h2>
        <p className="max-w-[560px] text-center text-[17px] leading-relaxed text-neutral-600 text-pretty">
          Upload your next solicitation and see it shredded into a working compliance matrix.
        </p>
        <Link
          href="/proposals/new"
          className="mt-1 flex h-[50px] items-center justify-center rounded-md bg-primary-600 px-8 text-[15px] font-medium text-white transition-colors hover:bg-primary-800"
        >
          Upload an RFP
        </Link>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer className="flex flex-col items-center justify-between gap-4 border-t border-neutral-100 bg-white px-6 py-9 sm:flex-row lg:px-[120px]">
        <div className="flex items-center gap-2.5">
          <ShieldCheck className="h-5 w-5 text-neutral-400" strokeWidth={1.5} />
          {/* Placeholders, not invented details — fill these in before launch. */}
          <span className="text-[13px] text-neutral-400">ProposalAI · [YOUR COMPANY], [YOUR CITY]</span>
        </div>
        <nav className="flex items-center gap-7">
          <Link href="/security" className="text-[13px] text-neutral-400 hover:text-neutral-600">Security</Link>
          <Link href="/request-access" className="text-[13px] text-neutral-400 hover:text-neutral-600">Request access</Link>
          <Link href="/login" className="text-[13px] text-neutral-400 hover:text-neutral-600">Sign in</Link>
        </nav>
      </footer>
    </div>
  )
}
