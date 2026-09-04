/**
 * 银河麒麟系统渲染适配工具
 * 针对银河麒麟系统优化Three.js渲染性能
 */
import * as THREE from 'three'

export class KylinOSRenderer {
  private isKylinOS: boolean = false
  private renderer: THREE.WebGLRenderer | null = null

  constructor() {
    this.detectKylinOS()
  }

  /**
   * 检测是否为银河麒麟系统
   */
  private detectKylinOS(): void {
    // 检测用户代理或系统信息
    const userAgent = navigator.userAgent.toLowerCase()
    const platform = navigator.platform.toLowerCase()
    
    if (userAgent.includes('kylin') || platform.includes('kylin') || 
        userAgent.includes('neokylin') || platform.includes('neokylin')) {
      this.isKylinOS = true
    }
    
    // 也可以通过API检测
    // @ts-ignore
    if (window.kylinOS || window.neokylinOS) {
      this.isKylinOS = true
    }
  }

  /**
   * 创建适配银河麒麟系统的渲染器
   */
  createRenderer(canvas: HTMLCanvasElement): THREE.WebGLRenderer {
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: this.isKylinOS ? 'high-performance' : 'default',
      preserveDrawingBuffer: false // 优化内存
    })

    if (this.isKylinOS) {
      // 银河麒麟系统优化配置
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5)) // 限制像素比
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = THREE.PCFSoftShadowMap
      
      // 启用硬件加速
      renderer.setClearColor(0xf0f0f0, 1)
      
      // 优化渲染设置
      renderer.sortObjects = true
    } else {
      // 标准配置
      renderer.setPixelRatio(window.devicePixelRatio)
    }

    this.renderer = renderer
    return renderer
  }

  /**
   * 优化场景性能（银河麒麟系统）
   */
  optimizeScene(scene: THREE.Scene): void {
    if (!this.isKylinOS) return

    // 限制场景复杂度
    const maxObjects = 100
    let objectCount = 0
    
    scene.traverse((object) => {
      if (object instanceof THREE.Mesh) {
        objectCount++
        
        // 优化几何体
        if (object.geometry) {
          object.geometry.computeBoundingSphere()
        }
        
        // 优化材质
        if (object.material instanceof THREE.Material) {
          object.material.needsUpdate = false
        }
      }
    })

    // 如果对象过多，发出警告
    if (objectCount > maxObjects) {
      console.warn(`场景对象过多 (${objectCount})，可能影响性能`)
    }
  }

  /**
   * 优化动画性能
   */
  optimizeAnimation(clock: THREE.Clock, maxFPS: number = 60): boolean {
    if (!this.isKylinOS) return true

    // 限制帧率以优化性能
    const elapsed = clock.getElapsedTime()
    const targetInterval = 1.0 / maxFPS
    
    return elapsed >= targetInterval
  }

  /**
   * 获取推荐的渲染设置
   */
  getRecommendedSettings(): {
    pixelRatio: number
    shadowMapEnabled: boolean
    antialias: boolean
    maxFPS: number
  } {
    if (this.isKylinOS) {
      return {
        pixelRatio: 1.5,
        shadowMapEnabled: true,
        antialias: true,
        maxFPS: 60
      }
    } else {
      return {
        pixelRatio: window.devicePixelRatio,
        shadowMapEnabled: true,
        antialias: true,
        maxFPS: 60
      }
    }
  }

  /**
   * 检查WebGL支持
   */
  checkWebGLSupport(): boolean {
    try {
      const canvas = document.createElement('canvas')
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
      return !!gl
    } catch (e) {
      return false
    }
  }

  /**
   * 获取系统信息
   */
  getSystemInfo(): {
    isKylinOS: boolean
    webglSupported: boolean
    userAgent: string
    platform: string
  } {
    return {
      isKylinOS: this.isKylinOS,
      webglSupported: this.checkWebGLSupport(),
      userAgent: navigator.userAgent,
      platform: navigator.platform
    }
  }
}

export const kylinOSRenderer = new KylinOSRenderer()





