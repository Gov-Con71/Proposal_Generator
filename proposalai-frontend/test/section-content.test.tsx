/**
 * SectionContent renders a drafted section's Markdown (headings, bullets,
 * bold spans — see backend draft_writer._SECTION_SYSTEM_PROMPT) as real DOM
 * elements. Before this existed, the workspace's only view of section content
 * was a contentEditable div interpolating the raw string, so a drafted
 * section literally showed "##", "-", and "**" characters — the same
 * symbols-bleeding-into-output bug already fixed on the export side.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SectionContent } from '@/components/ui/section-content'

describe('SectionContent', () => {
  it('renders an ATX heading as a heading element, not literal text', () => {
    render(<SectionContent content="## Technical Approach" />)
    const heading = screen.getByRole('heading', { name: 'Technical Approach' })
    expect(heading).toBeInTheDocument()
  })

  it('renders a bullet list as real list items', () => {
    render(<SectionContent content={'- First point\n- Second point'} />)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('First point')
    expect(items[1]).toHaveTextContent('Second point')
  })

  it('renders a bold span as a <strong> element', () => {
    render(<SectionContent content="Certified by **CMMC Level 2** for this engagement." />)
    const strong = screen.getByText('CMMC Level 2')
    expect(strong.tagName).toBe('STRONG')
  })

  it('does not leak raw Markdown syntax characters into the rendered text', () => {
    const { container } = render(
      <SectionContent
        content={
          '## Understanding of the Requirement\n\n' +
          'We understand the requirement.\n\n' +
          '## Technical Approach\n\n' +
          'Our approach includes:\n' +
          '- Certified technicians perform teardown and inspection\n' +
          '- OEM-spec parts sourced from approved vendors\n\n' +
          '**Differentiators:** active CMMC Level 2 certification.'
        }
      />
    )
    const text = container.textContent ?? ''
    expect(text).not.toContain('##')
    expect(text).not.toContain('**')
    expect(text).not.toMatch(/\n- /)
    expect(text).toContain('Certified technicians perform teardown')
    expect(text).toContain('Differentiators:')
  })

  it('renders multiple heading levels distinctly', () => {
    render(<SectionContent content={'## Section Heading\n\n### Subsection Heading'} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Section Heading' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'Subsection Heading' })).toBeInTheDocument()
  })

  it('preserves [Req N] traceability tags — useful in the internal review view, unlike the customer-facing export', () => {
    render(<SectionContent content="We meet this standard. [Req 3]" />)
    expect(screen.getByText(/\[Req 3\]/)).toBeInTheDocument()
  })

  it('renders empty content without crashing', () => {
    const { container } = render(<SectionContent content="" />)
    expect(container).toBeInTheDocument()
  })

  it('renders plain prose with no Markdown constructs as a normal paragraph', () => {
    render(<SectionContent content="The contractor shall deliver widgets on schedule." />)
    expect(screen.getByText('The contractor shall deliver widgets on schedule.')).toBeInTheDocument()
  })
})
