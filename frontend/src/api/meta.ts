import type { MetaStatus } from '@/types'
import { apiGet } from './client'

export const getMetaStatus = () => apiGet<MetaStatus>('/api/meta/status')
