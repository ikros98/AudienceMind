/* eslint-disable react/no-unknown-property */
import { Text } from "@react-three/drei";
import { FluidGlass } from "./FluidGlass";

/** A colored rectangle representing a mock dashboard panel */
function Panel({
  position,
  color,
  width,
  height,
}: {
  position: [number, number, number];
  color: string;
  width: number;
  height: number;
}) {
  return (
    <mesh position={position}>
      <planeGeometry args={[width, height]} />
      <meshBasicMaterial color={color} opacity={0.7} transparent />
    </mesh>
  );
}

/** Inner 3D content: a mock dashboard layout behind the lens */
function DashboardContent() {
  return (
    <group>
      {/* Gradient background plane */}
      <mesh position={[0, 0, -4]}>
        <planeGeometry args={[12, 8]} />
        <meshBasicMaterial color="#0c0e18" />
      </mesh>

      {/* Dashboard header bar */}
      <Panel position={[0, 1.5, -3]} color="#1a1f35" width={8} height={0.5} />
      <Text
        position={[-2.5, 1.5, -2.9]}
        fontSize={0.14}
        color="#7ee7ff"
        anchorX="left"
        anchorY="middle"
      >
        AudienceMind Dashboard
      </Text>

      {/* Left sidebar panel */}
      <Panel position={[-2.8, -0.1, -3]} color="#111628" width={2.0} height={2.6} />
      <Text position={[-2.8, 0.8, -2.9]} fontSize={0.1} color="#a78bfa" anchorX="center" anchorY="middle">
        Personas
      </Text>
      <Panel position={[-2.8, 0.4, -2.8]} color="#1e2440" width={1.6} height={0.25} />
      <Panel position={[-2.8, 0.0, -2.8]} color="#1e2440" width={1.6} height={0.25} />
      <Panel position={[-2.8, -0.4, -2.8]} color="#1e2440" width={1.6} height={0.25} />

      {/* Main content area with chart mockup */}
      <Panel position={[0.5, 0.3, -3]} color="#111628" width={4.4} height={1.6} />
      <Text position={[-0.8, 0.9, -2.9]} fontSize={0.1} color="#4a6fff" anchorX="left" anchorY="middle">
        Knowledge Graph
      </Text>
      {/* Chart bars */}
      <Panel position={[-0.4, 0.0, -2.8]} color="#4a6fff" width={0.3} height={0.8} />
      <Panel position={[0.1, 0.0, -2.8]} color="#7ee7ff" width={0.3} height={1.0} />
      <Panel position={[0.6, 0.0, -2.8]} color="#a78bfa" width={0.3} height={0.6} />
      <Panel position={[1.1, 0.0, -2.8]} color="#c7ccff" width={0.3} height={0.9} />
      <Panel position={[1.6, 0.0, -2.8]} color="#4a6fff" width={0.3} height={0.7} />

      {/* Bottom stats row */}
      <Panel position={[-1.5, -1.2, -3]} color="#111628" width={2.4} height={0.7} />
      <Panel position={[1.2, -1.2, -3]} color="#111628" width={3.0} height={0.7} />
      <Text position={[-1.5, -1.0, -2.9]} fontSize={0.09} color="#7ee7ff" anchorX="center" anchorY="middle">
        42 Nodes  |  128 Edges
      </Text>
      <Text position={[1.2, -1.0, -2.9]} fontSize={0.09} color="#a78bfa" anchorX="center" anchorY="middle">
        Simulation: 3 Personas Active
      </Text>

      {/* Lighting */}
      <ambientLight intensity={0.8} />
    </group>
  );
}

export function LensScene() {
  return (
    <FluidGlass
      mode="lens"
      pages={1}
      className="lens-canvas-wrapper"
    >
      <DashboardContent />
    </FluidGlass>
  );
}
