'use client'
import { useCallback, useState } from 'react'
import { useDropzone, type FileRejection } from 'react-dropzone'
import { CloudUpload, FileText, Loader2, Trash2, AlertTriangle, Library } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { EmptyState, ErrorState, errorMessage } from '@/components/ui/state'
import { cn } from '@/lib/utils/cn'
import { formatDate } from '@/lib/utils/format'
import { useHistorySources, useHistoryUpload, useHistoryRemove, useHistoryPromote } from '@/lib/hooks'

const MAX_SIZE = 50 * 1024 * 1024

interface EvidenceUploaderProps {
  /** Omit for the long-term library; pass an id to scope to one bid's
   *  supporting documents. Threaded straight through to the API and the
   *  query cache key. */
  proposalId?: string
  emptyTitle: string
  emptyMessage: string
}

/** Dropzone + source list over one past-performance pool.
 *
 *  Shared by the library page and the in-flow supporting-documents step: the
 *  two differ only in which pool they address and what they say when empty,
 *  so the upload, list, and remove behaviour lives here once. */
export function EvidenceUploader({ proposalId, emptyTitle, emptyMessage }: EvidenceUploaderProps) {
  const { data: sources = [], isLoading, isError, error, refetch } = useHistorySources(proposalId)
  const upload = useHistoryUpload(proposalId)
  const remove = useHistoryRemove(proposalId)
  const promote = useHistoryPromote(proposalId)
  const [rejected, setRejected] = useState<string | null>(null)

  // Uploads run one at a time. Each costs a parse plus an embedding call, and
  // firing a whole drop at once is exactly what gets rate-limited on a
  // concurrency-metered provider.
  const onDrop = useCallback(
    async (files: File[]) => {
      setRejected(null)
      for (const file of files) {
        try {
          await upload.mutateAsync(file)
        } catch {
          // The mutation's own error state renders below; keep going so one
          // unreadable file doesn't silently drop the rest of the batch.
        }
      }
    },
    [upload]
  )

  const onDropRejected = useCallback((fileRejections: FileRejection[]) => {
    const first = fileRejections[0]
    const reason = first?.errors[0]
    setRejected(
      reason?.code === 'file-too-large'
        ? `“${first.file.name}” is larger than 50MB.`
        : `“${first?.file.name}” isn’t a PDF, DOCX or TXT file.`
    )
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/plain': ['.txt'],
    },
    maxSize: MAX_SIZE,
    disabled: upload.isPending,
  })

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div
          {...getRootProps()}
          className={cn(
            'flex flex-col items-center justify-center gap-2 py-10 px-4 rounded-lg border border-dashed transition-colors cursor-pointer',
            upload.isPending
              ? 'border-[var(--border-subtle)] cursor-wait'
              : isDragActive
                ? 'border-primary-600 bg-primary-50'
                : 'border-[var(--border-default)] hover:border-primary-400 hover:bg-[var(--bg-secondary)]'
          )}
        >
          <input {...getInputProps()} />
          {upload.isPending ? (
            <>
              <Loader2 className="w-6 h-6 text-primary-600 animate-spin" />
              <p className="text-sm font-medium">Reading and indexing…</p>
              <p className="text-xs text-[var(--text-tertiary)]">
                Extracting text, then embedding it for retrieval.
              </p>
            </>
          ) : (
            <>
              <CloudUpload className="w-6 h-6 text-[var(--text-tertiary)]" />
              <p className="text-sm font-medium">Drop past performance documents here</p>
              <p className="text-xs text-[var(--text-tertiary)]">
                PDF, DOCX or TXT up to 50MB — several at once is fine
              </p>
            </>
          )}
        </div>

        {rejected && (
          <div className="flex items-center gap-2 mt-3 px-3 py-2 rounded bg-warning-50">
            <AlertTriangle className="w-3.5 h-3.5 text-warning-600 shrink-0" />
            <span className="text-xs text-warning-800">{rejected}</span>
          </div>
        )}

        {upload.isError && (
          <div className="flex items-center gap-2 mt-3 px-3 py-2 rounded bg-danger-50">
            <AlertTriangle className="w-3.5 h-3.5 text-danger-600 shrink-0" />
            <span className="text-xs text-danger-800">{errorMessage(upload.error)}</span>
          </div>
        )}

        {promote.isError && (
          <div className="flex items-center gap-2 mt-3 px-3 py-2 rounded bg-danger-50">
            <AlertTriangle className="w-3.5 h-3.5 text-danger-600 shrink-0" />
            <span className="text-xs text-danger-800">{errorMessage(promote.error)}</span>
          </div>
        )}
      </Card>

      <Card>
        {isError ? (
          <ErrorState title="Could not load your documents" error={error} onRetry={() => refetch()} />
        ) : isLoading ? (
          <div className="flex items-center justify-center gap-2 py-10">
            <Loader2 className="w-4 h-4 animate-spin text-[var(--text-tertiary)]" />
            <span className="text-xs text-[var(--text-tertiary)]">Loading…</span>
          </div>
        ) : sources.length === 0 ? (
          <EmptyState
            title={emptyTitle}
            message={emptyMessage}
            icon={<FileText className="w-5 h-5 text-[var(--text-tertiary)]" />}
          />
        ) : (
          <div className="flex flex-col">
            <div className="flex items-center justify-between px-1 pb-2 mb-1 border-b border-[var(--border-subtle)]">
              <span className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
                {sources.length} document{sources.length === 1 ? '' : 's'}
              </span>
              <span className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
                Indexed
              </span>
            </div>
            {sources.map((s) => (
              <div
                key={s.sourceName}
                className="flex items-center gap-3 py-2.5 border-b border-[var(--border-subtle)] last:border-0"
              >
                <FileText className="w-4 h-4 text-[var(--text-tertiary)] shrink-0" />
                <div className="flex flex-col min-w-0 flex-1">
                  <span className="text-xs font-medium truncate">{s.sourceName}</span>
                  <span className="text-[10px] text-[var(--text-tertiary)]">
                    {/* Chunks are the unit retrieval actually searches, so this
                        is the honest measure of how much evidence was indexed. */}
                    {s.chunks} passage{s.chunks === 1 ? '' : 's'} · {formatDate(s.createdAt)}
                  </span>
                </div>
                {/* Only the bid pool can promote — the library page has
                    nowhere further to send a document. */}
                {proposalId && (
                  <button
                    onClick={() => promote.mutate(s.sourceName)}
                    disabled={promote.isPending}
                    title="Save to your permanent library"
                    aria-label={`Save ${s.sourceName} to library`}
                    className="w-8 h-8 flex items-center justify-center rounded text-[var(--text-tertiary)] hover:text-primary-600 hover:bg-primary-50 transition-colors disabled:opacity-50"
                  >
                    {promote.isPending && promote.variables === s.sourceName ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Library className="w-3.5 h-3.5" />
                    )}
                  </button>
                )}
                <button
                  onClick={() => remove.mutate(s.sourceName)}
                  disabled={remove.isPending}
                  aria-label={`Remove ${s.sourceName}`}
                  className="w-8 h-8 flex items-center justify-center rounded text-[var(--text-tertiary)] hover:text-danger-600 hover:bg-danger-50 transition-colors disabled:opacity-50"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
