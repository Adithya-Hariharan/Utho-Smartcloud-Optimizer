import { useRecommendations } from './data'
import { useUi } from '../store/ui'

/** Recommendations for the preset selected in the header. */
export function useRecs() {
  const preset = useUi((s) => s.preset)
  return useRecommendations(preset)
}
