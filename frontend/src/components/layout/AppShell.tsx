// 메뉴 4개(설계서 §5.4 공통) + 상태 바 + 본문. 라우트는 HashRouter 라 서버가 경로를 몰라도 된다.
import { Layout, Menu } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { ErrorBoundary } from './ErrorBoundary'
import { StatusBar } from './StatusBar'

const ITEMS = [
  { key: '/hub', label: '데이터 허브' },
  { key: '/backtest', label: '백테스트' },
  { key: '/optimize', label: '최적화' },
  { key: '/runs', label: '실행 기록' },
]

export function AppShell() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  // /hub/overview 처럼 하위 경로도 같은 메뉴로 잡는다
  // 결과·비교 화면은 실행 기록 메뉴 아래로 본다
  const menuPath = pathname.startsWith('/results') || pathname.startsWith('/compare') ? '/runs' : pathname
  const selected = ITEMS.find((i) => menuPath === i.key || menuPath.startsWith(`${i.key}/`))?.key

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider width={168} theme="light" breakpoint="lg" collapsedWidth={0}>
        <div style={{ padding: '16px', fontWeight: 600 }}>백테스트 스튜디오</div>
        <Menu mode="inline" selectedKeys={selected ? [selected] : []} items={ITEMS} onClick={(e) => navigate(e.key)} />
      </Layout.Sider>
      <Layout>
        <Layout.Header style={{ background: 'transparent', padding: '0 24px', height: 48, lineHeight: '48px' }}>
          <StatusBar />
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          <ErrorBoundary resetKey={pathname}><Outlet /></ErrorBoundary>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
