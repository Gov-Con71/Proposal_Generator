import ReactMarkdown from 'react-markdown'
import { cn } from '@/lib/utils/cn'

interface SectionContentProps {
  content: string
  className?: string
}

/** Read-only render of a drafted section's Markdown (the AI writer's `##`
 *  headings, `-` bullets, and `**bold**` spans — see draft_writer.
 *  _SECTION_SYSTEM_PROMPT on the backend). Before this existed, the
 *  workspace only ever showed that Markdown as literal, unrendered text —
 *  the same "symbols bleed into the output" bug already fixed for exports.
 *
 *  Styled with plain Tailwind child selectors rather than the typography
 *  plugin (not installed, and this app's neutral/primary tokens don't match
 *  its generic `prose` defaults closely enough to be worth adding just for
 *  one view). */
export function SectionContent({ content, className }: SectionContentProps) {
  return (
    <div
      className={cn(
        'text-sm text-neutral-700 leading-relaxed',
        '[&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-neutral-800 [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:first:mt-0',
        '[&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-neutral-800 [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:first:mt-0',
        '[&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-neutral-800 [&_h3]:mt-3 [&_h3]:mb-1.5',
        '[&_p]:mb-3 [&_p]:last:mb-0',
        '[&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ul]:space-y-1',
        '[&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_ol]:space-y-1',
        '[&_strong]:font-semibold [&_strong]:text-neutral-800',
        className
      )}
    >
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}
