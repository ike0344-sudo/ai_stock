// 알림 규칙 표 (§5.4): 규칙, 켜기/끄기, 마지막 발송
import { useQueryClient } from '@tanstack/react-query'
import { App, Switch, Table, Tag, Typography } from 'antd'
import { patchAlert } from '@/api/hub'
import { DASH, fmtTs } from '@/lib/format'
import type { AlertRule } from '@/types/data'

export function AlertRulesTable({ rules }: { rules: AlertRule[] }) {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const toggle = async (id: AlertRule['id'], enabled: boolean) => {
    try {
      await patchAlert(id, { enabled })
      void qc.invalidateQueries({ queryKey: ['hub'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <Table<AlertRule>
      data-testid="alert-rules"
      size="small"
      rowKey="id"
      pagination={false}
      dataSource={rules}
      columns={[
        { title: '규칙', render: (_, r) => <><strong>{r.title}</strong><br /><Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.when}</Typography.Text></> },
        {
          title: '켜기/끄기',
          render: (_, r) => (
            <>
              <Switch size="small" checked={r.enabled} onChange={(v) => toggle(r.id, v)} aria-label={`${r.title} 켜기/끄기`} />{' '}
              {r.enabled !== r.default_enabled && <Tag>기본값과 다름</Tag>}
            </>
          ),
        },
        { title: '마지막 발송', dataIndex: 'last_sent', render: (t: string | null) => fmtTs(t) },
        { title: '마지막 내용', dataIndex: 'last_message', render: (m: string | null) => m ?? DASH },
      ]}
    />
  )
}
