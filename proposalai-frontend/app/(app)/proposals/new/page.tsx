'use client'
import { useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useDropzone, type FileRejection } from 'react-dropzone'
import { CloudUpload, FileText, CheckCircle2, Trash2, ArrowLeft, AlertTriangle, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
// Remove: import { Select } from '@/components/ui/input'
import { Card, StepIndicator } from '@/components/ui/card'
import { cn } from '@/lib/utils/cn'
import { formatFileSize } from '@/lib/utils/format'
import { documentsApi } from '@/lib/api'
import type { Step } from '@/components/ui/card'

const MAX_SIZE = 50 * 1024 * 1024

const STEPS: Step[] = [
  { label: 'Upload RFP', status: 'active' },
  { label: 'Analyze',    status: 'pending' },
  { label: 'Outline',    status: 'pending' },
  { label: 'Review',     status: 'pending' },
]

const CONTRACT_TYPES = [
  { value: 'ffp',  label: 'Firm Fixed Price (FFP)' },
  { value: 'cpff', label: 'Cost Plus Fixed Fee (CPFF)' },
  { value: 'tm',   label: 'Time & Materials (T&M)' },
  { value: 'idiq', label: 'IDIQ' },
]

export default function UploadPage() {
  const router = useRouter()
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  // NOTE: this metadata is not submitted yet — POST /documents/upload takes the
  // file only, and the title/agency/solicitation are parsed from the document
  // during ingestion. Wiring these through needs a backend contract change.
  const [form, setForm] = useState({
    title: '',
    agency: '',
    solicitationNumber: '',
    deadline: '',
    contractType: 'ffp',
    naicsCode: '',
  })

  const onDrop = useCallback((accepted: File[]) => {
    if (accepted[0]) {
      setFile(accepted[0])
      setError(null)
    }
  }, [])

  // Client-side error boundary (Story 2.1): surface too-large / wrong-type before hitting the API.
  const onDropRejected = useCallback((rejections: FileRejection[]) => {
    const code = rejections[0]?.errors[0]?.code
    setError(
      code === 'file-too-large' ? 'File exceeds the 50MB limit.'
      : code === 'file-invalid-type' ? 'Unsupported file type — use PDF, DOCX, or TXT.'
      : rejections[0]?.errors[0]?.message ?? 'File rejected.'
    )
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: { 'application/pdf': ['.pdf'], 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'], 'text/plain': ['.txt'] },
    maxFiles: 1,
    maxSize: MAX_SIZE,
  })

  function update(key: string, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  // Streams the file to the backend, then advances to the processing view.
  async function handleContinue() {
    if (!file) {
      setError('Select an RFP document to upload before continuing.')
      return
    }
    setError(null)
    setUploading(true)
    setProgress(0)
    try {
      const res = await documentsApi.upload(file, setProgress)
      // Guard the handoff: without an id the next step would stream against
      // /proposals/undefined/… and 422 on every poll.
      if (!res.rfpId) {
        setError('The server accepted the upload but returned no document id. Please retry.')
        setUploading(false)
        return
      }
      router.push(`/proposals/new/process?rfp=${res.rfpId}`)
    } catch (e) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      const detail = err.response?.data?.detail
      const status = err.response?.status
      setError(
        status === 401 ? 'Your session expired — please sign in again.'
        : detail
        ?? (status === 413 ? 'File exceeds the 50MB limit.'
          : status === 415 ? 'Unsupported file type — use PDF, DOCX, or TXT.'
          : 'Upload failed. Please try again.')
      )
      setUploading(false)
    }
  }

  return (
    <div className="content-narrow">
      <Link href="/dashboard" className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] mb-4 transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" /> Back to dashboard
      </Link>

      <StepIndicator steps={STEPS} className="mb-6" />

      {/* Upload zone */}
      <Card className="mb-4">
        <div
          {...getRootProps()}
          className={cn(
            'border border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors',
            isDragActive
              ? 'border-primary-600 bg-primary-50'
              : 'border-[var(--border-default)] hover:border-primary-600 hover:bg-[var(--bg-secondary)]'
          )}
        >
          <input {...getInputProps()} />
          <div className="w-12 h-12 rounded-full bg-primary-50 flex items-center justify-center mx-auto mb-3">
            <CloudUpload className="w-6 h-6 text-primary-600" />
          </div>
          <p className="text-sm font-medium text-[var(--text-primary)] mb-1">
            Drop your RFP, RFQ or SOW here
          </p>
          <p className="text-xs text-[var(--text-tertiary)] mb-3">PDF, DOCX, or TXT files up to 50MB</p>
          <Button variant="default" size="sm">Browse files</Button>
        </div>

        {file && (
          <div className="flex items-center gap-3 mt-3 px-3 py-2.5 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-subtle)]">
            <FileText className="w-5 h-5 text-danger-600 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium truncate">{file.name}</p>
              <p className="text-[10px] text-[var(--text-tertiary)]">{formatFileSize(file.size)}</p>
            </div>
            <CheckCircle2 className="w-4 h-4 text-success-400 shrink-0" />
            <button onClick={() => setFile(null)} className="text-[var(--text-tertiary)] hover:text-danger-600 transition-colors">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Demo: show pre-loaded file if none uploaded */}
        {!file && (
          <div className="flex items-center gap-3 mt-3 px-3 py-2.5 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-subtle)]">
            <FileText className="w-5 h-5 text-danger-600 shrink-0" />
            <div className="flex-1">
              <p className="text-xs font-medium">RFP_823-A.pdf</p>
              <p className="text-[10px] text-[var(--text-tertiary)]">1.4 MB</p>
            </div>
            <CheckCircle2 className="w-4 h-4 text-success-400 shrink-0" />
            <button className="text-[var(--text-tertiary)] hover:text-danger-600 transition-colors">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
        {/* Upload progress */}
        {uploading && (
          <div className="mt-3">
            <div className="flex justify-between text-xs text-[var(--text-secondary)] mb-1.5">
              <span className="flex items-center gap-1.5"><Loader2 className="w-3 h-3 animate-spin" /> Uploading…</span>
              <span className="font-medium text-primary-600">{progress}%</span>
            </div>
            <div className="h-1.5 bg-[var(--bg-secondary)] rounded-full overflow-hidden">
              <div className="h-full bg-primary-600 rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {/* Error boundary */}
        {error && (
          <div className="flex items-center gap-2 mt-3 px-3 py-2.5 bg-danger-50 border border-danger-200 rounded-lg">
            <AlertTriangle className="w-4 h-4 text-danger-600 shrink-0" />
            <p className="text-xs text-danger-700">{error}</p>
          </div>
        )}
      </Card>

      {/* Auto-detected solicitation details */}
      <Card className="mb-6">
        <h3 className="text-sm font-medium mb-0.5">Solicitation details <span className="font-normal text-[var(--text-tertiary)]">(auto-detected)</span></h3>
        <p className="text-xs text-[var(--text-tertiary)] mb-4">Review the extracted information below to ensure accuracy for AI compliance mapping.</p>

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <Input label="Title" value={form.title} onChange={(e) => update('title', e.target.value)} />
          </div>
          <Input label="Agency" value={form.agency} onChange={(e) => update('agency', e.target.value)} />
          <Input label="Solicitation #" value={form.solicitationNumber} onChange={(e) => update('solicitationNumber', e.target.value)} />
          <Input label="Deadline" type="date" value={form.deadline} onChange={(e) => update('deadline', e.target.value)} />
          
          {/* Replace Select with native select */}
          <div>
            <label className="block text-xs font-medium text-[var(--text-primary)] mb-1">
              Contract type
            </label>
            <select 
              value={form.contractType} 
              onChange={(e) => update('contractType', e.target.value)}
              className="w-full px-2 py-1.5 text-xs border border-[var(--border-default)] rounded-md bg-[var(--bg-primary)]"
            >
              {CONTRACT_TYPES.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          
          <div className="col-span-2">
            <Input label="NAICS Code" value={form.naicsCode} onChange={(e) => update('naicsCode', e.target.value)} />
          </div>
        </div>

        {/* AI confidence note */}
        <div className="flex items-center gap-2 mt-4 px-3 py-2 bg-primary-50 rounded-lg">
          <div className="w-5 h-5 rounded-full bg-primary-600 flex items-center justify-center shrink-0">
            <span className="text-[9px] text-white font-bold">AI</span>
          </div>
          <p className="text-xs text-primary-800">AI Extraction Complete — 98.2% confidence score for auto-detected metadata.</p>
        </div>
      </Card>

      <div className="flex justify-between">
        <Button variant="default" asChild>
          <Link href="/dashboard">Cancel</Link>
        </Button>
        <Button
          variant="primary"
          icon={uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowLeft className="w-3.5 h-3.5 rotate-180" />}
          iconPosition="right"
          disabled={uploading}
          onClick={handleContinue}
        >
          {uploading ? 'Uploading…' : 'Continue to Analysis'}
        </Button>
      </div>
    </div>
  )
}