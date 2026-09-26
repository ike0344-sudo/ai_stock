// 로그 뷰어 (§5.4): 2초 이어받기(offset), 자동 스크롤. 비밀값은 서버가 가려서 준다(jobrunner.mask) — 화면은 받은 그대로 보여준다.
import { Alert, Drawer, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { fetchJobLog } from '@/api/hub'
import type { JobRow } from '@/types'

const POLL_MS = 2000
const DONE = new Set(['succeeded', 'failed', 'cancelled'])

export function LogViewer({ job, onClose }: { job: JobRow | null; onClose: () => void }) {
  const [text, setText] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const box = useRef<HTMLPreElement>(null)
  const jobId = job?.job_id
  const finished = job ? DONE.has(job.status) : false

  useEffect(() => {
    if (!jobId) return
    let offset = 0
    let stop = false
    let timer: ReturnType<typeof setTimeout> | undefined
    setText('')
    setErr(null)
    const tick = async () => {
      try {
        const r = await fetchJobLog(jobId, offset)
        offset = r.next_offset
        if (r.text) setText((t) => t + r.text)
        setErr(null)
        // 끝난 작업은 로그를 다 받으면(eof) 그만 부른다
        if (finished && r.eof) return
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e))
      }
      if (!stop) timer = setTimeout(tick, POLL_MS)
    }
    void tick()
    return () => {
      stop = true
      if (timer) clearTimeout(timer)
    }
  }, [jobId, finished])

  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight // 자동 스크롤
  }, [text])

  return (
    <Drawer title={job ? `로그 — ${job.job_id}` : '로그'} open={!!job} onClose={onClose} size="large" destroyOnHidden>
      {err && <Alert type="warning" showIcon message={`로그를 못 받음: ${err}`} style={{ marginBottom: 8 }} />}
      <pre ref={box} data-testid="log-text" style={{ height: '75vh', overflow: 'auto', margin: 0, whiteSpace: 'pre-wrap', fontSize: 12 }}>
        {text || <Typography.Text type="secondary">(아직 출력 없음)</Typography.Text>}
      </pre>
    </Drawer>
  )
}
