// 빈 페이지 골격 — 무엇이 들어올지와 어느 모듈에서 채우는지만 적는다.
import { Card, Empty, Typography } from 'antd'

export function Placeholder({ title, note }: { title: string; note: string }) {
  return (
    <Card title={title}>
      <Empty description={<Typography.Text type="secondary">{note}</Typography.Text>} />
    </Card>
  )
}
