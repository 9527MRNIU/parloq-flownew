import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangleIcon, RefreshCwIcon } from 'lucide-react'
import { Button } from './ui'

type Props = { children: ReactNode }
type State = { failed: boolean }

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Parloq page render failed', error, info)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="app-error-boundary" role="alert">
        <AlertTriangleIcon size={28} aria-hidden="true" />
        <h1>页面暂时无法显示</h1>
        <p>当前页面发生了意外错误。刷新后可重新加载，未提交的表单内容可能不会保留。</p>
        <Button onClick={() => window.location.reload()}>
          <RefreshCwIcon size={16} aria-hidden="true" />
          刷新页面
        </Button>
      </main>
    )
  }
}
