// 다크 모드 — antd 알고리즘 + echarts 테마가 같이 바뀐다. 선택은 브라우저에 기억한다.
import { App as AntApp, ConfigProvider, theme } from 'antd'
import koKR from 'antd/locale/ko_KR'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

interface ThemeState {
  dark: boolean
  toggle: () => void
}

const KEY = 'studio.dark'
const Ctx = createContext<ThemeState>({ dark: false, toggle: () => undefined })

export const useDark = () => useContext(Ctx)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState(() => localStorage.getItem(KEY) === '1')
  useEffect(() => {
    localStorage.setItem(KEY, dark ? '1' : '0')
    document.body.style.background = dark ? '#141414' : '#f5f5f5'
  }, [dark])
  const value = useMemo(() => ({ dark, toggle: () => setDark((d) => !d) }), [dark])
  return (
    <Ctx.Provider value={value}>
      <ConfigProvider locale={koKR} theme={{ algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm }}>
        <AntApp>{children}</AntApp>
      </ConfigProvider>
    </Ctx.Provider>
  )
}
