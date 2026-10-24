import { useSearchParams } from 'react-router-dom'

/** The resource drawer is driven by ?r=<resource_id>, so any page can deep-link to it. */
export function useResourceDrawer() {
  const [params, setParams] = useSearchParams()
  const id = params.get('r')
  const open = (resourceId: string) =>
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.set('r', resourceId)
      n.delete('tab')
      return n
    })
  const close = () =>
    setParams((p) => {
      const n = new URLSearchParams(p)
      n.delete('r')
      n.delete('tab')
      return n
    })
  return { id, open, close }
}
