import { cloneVNode, defineComponent, provide, shallowReactive, watch, type PropType, type VNode } from 'vue'
import { routeLocationKey, type RouteLocationNormalizedLoaded } from 'vue-router'

// A cached view must keep its own route. The global route belongs to the visible
// view and must never drive a hidden Conversation or Mission's watchers.
export default defineComponent({
  name: 'CachedWorkspaceView',
  props: {
    view: { type: Object as PropType<VNode>, required: true },
    viewRoute: { type: Object as PropType<RouteLocationNormalizedLoaded>, required: true }
  },
  setup(props) {
    const snapshot = shallowReactive({ ...props.viewRoute })
    provide(routeLocationKey, snapshot)
    watch(() => props.viewRoute, next => Object.assign(snapshot, next), { flush: 'sync' })
    return () => cloneVNode(props.view)
  }
})
