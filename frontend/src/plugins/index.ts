import { PluginUiExtensionRegistry } from './registry'
import { legalUiExtension } from './legal'
import { industrialUiExtension } from './industrial'

export const pluginUiExtensions = new PluginUiExtensionRegistry()
pluginUiExtensions.register(legalUiExtension)
pluginUiExtensions.register(industrialUiExtension)
