import { CapsuleNav } from '../components/CapsuleNav';
import { Hero } from '../components/Hero';
import { SocialProof } from '../components/SocialProof';
import { Features } from '../components/Features';
import { GlassShowcase } from '../components/GlassShowcase';
import { FAQ } from '../components/FAQ';
import { Footer } from '../components/Footer';

export default function HomePage() {
  return (
    <>
      <CapsuleNav />
      <main>
        <Hero />
        <SocialProof />
        <Features />
        <GlassShowcase />
        <FAQ />
      </main>
      <Footer />
    </>
  );
}
