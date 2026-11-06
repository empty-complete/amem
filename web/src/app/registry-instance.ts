import { corePlugin } from "./core-plugin";
import { createRegistry } from "./registry";

/** Реестр приложения; плагины собираются вместе с оболочкой (динамическая загрузка — после v1). */
export const registry = createRegistry();
registry.register(corePlugin);
