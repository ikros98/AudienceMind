/* eslint-disable react/no-unknown-property */
import { memo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { createPortal, useFrame, useThree } from "@react-three/fiber";
import { useFBO, MeshTransmissionMaterial } from "@react-three/drei";
import { easing } from "maath";

export interface ModeWrapperProps {
  children?: ReactNode;
  geometry: THREE.BufferGeometry;
  lockToBottom?: boolean;
  followPointer?: boolean;
  scale?: number;
  ior?: number;
  thickness?: number;
  anisotropy?: number;
  chromaticAberration?: number;
  transmission?: number;
  roughness?: number;
}

export const ModeWrapper = memo(function ModeWrapper({
  children,
  geometry,
  lockToBottom = false,
  followPointer = false,
  scale: scaleProp = 1,
  ior = 1.15,
  thickness = 5,
  anisotropy = 0.1,
  chromaticAberration = 0.05,
  transmission = 1,
  roughness = 0,
}: ModeWrapperProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const bgRef = useRef<THREE.Mesh>(null);

  // Offscreen scene for portal rendering
  const [offscreenScene] = useState(() => new THREE.Scene());

  const fbo = useFBO(1024, 1024);
  const viewport = useThree((s) => s.viewport);
  const camera = useThree((s) => s.camera);

  useFrame((state, delta) => {
    const mesh = meshRef.current;
    if (!mesh) return;

    // Position the glass mesh
    if (lockToBottom) {
      mesh.position.y = -viewport.height / 2 + 0.5;
      mesh.position.x = 0;
    } else if (followPointer) {
      const pointerX = state.pointer.x * (viewport.width / 2);
      const pointerY = state.pointer.y * (viewport.height / 2);
      easing.damp3(
        mesh.position,
        [pointerX, pointerY, 0],
        0.15,
        delta,
      );
    }

    // Render the offscreen scene to the FBO
    const renderer = state.gl;
    renderer.setRenderTarget(fbo);
    renderer.render(offscreenScene, camera);
    renderer.setRenderTarget(null);

    // Apply FBO texture to background plane
    const bg = bgRef.current;
    if (bg) {
      const mat = bg.material as THREE.MeshBasicMaterial;
      mat.map = fbo.texture;
      mat.needsUpdate = true;
    }
  });

  return (
    <>
      {/* Portal: children render into the offscreen scene */}
      {createPortal(children, offscreenScene)}

      {/* Fullscreen background plane showing the FBO texture */}
      <mesh ref={bgRef} position={[0, 0, -1]}>
        <planeGeometry args={[viewport.width, viewport.height]} />
        <meshBasicMaterial />
      </mesh>

      {/* Glass mesh */}
      <mesh ref={meshRef} geometry={geometry} scale={scaleProp}>
        <MeshTransmissionMaterial
          buffer={fbo.texture}
          ior={ior}
          thickness={thickness}
          anisotropy={anisotropy}
          chromaticAberration={chromaticAberration}
          transmission={transmission}
          roughness={roughness}
          color="#ffffff"
          transmissionSampler={false}
          samples={6}
          resolution={512}
        />
      </mesh>
    </>
  );
});
