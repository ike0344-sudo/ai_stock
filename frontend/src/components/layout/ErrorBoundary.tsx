// 화면 하나가 그리다 죽어도 앱 전체가 하얗게 되지 않게 — 오류 문구를 보여주고, 다른 메뉴로 가면 다시 살아난다(resetKey = 주소).
import { Alert } from 'antd'
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props { children: ReactNode; resetKey?: string }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }
  static getDerivedStateFromError(error: Error): State { return { error } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('화면 오류', error, info.componentStack) }
  componentDidUpdate(prev: Props) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }) }
  render() {
    if (this.state.error) {
      return <Alert type="error" showIcon data-testid="screen-crash" message="이 화면을 그리다 오류가 났습니다" description={`${this.state.error.name}: ${this.state.error.message} — 다른 메뉴로 이동하면 다시 열립니다. 이 문구를 알려 주세요.`} />
    }
    return this.props.children
  }
}
