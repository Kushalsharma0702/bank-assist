#!/usr/bin/env python3
"""
Banking Voice Assistant Enhancement Setup Script

Installs all dependencies for:
- Interruption logic (WebSocket, real-time VAD)
- Advanced STT preprocessing (noise reduction, VAD, AGC)
- Humanized TTS (SSML, prosody control)

Compatible with Windows, macOS, and Linux
"""

import subprocess
import sys
import os
import platform


def print_header(message):
    print(f"\n{'=' * 50}")
    print(f"  {message}")
    print(f"{'=' * 50}\n")


def print_step(message):
    print(f"📋 {message}")


def print_success(message):
    print(f"✅ {message}")


def print_warning(message):
    print(f"⚠️  {message}")


def print_error(message):
    print(f"❌ {message}")


def run_command(cmd, description=""):
    """Run a shell command and report status"""
    try:
        if description:
            print_step(description)
        
        if isinstance(cmd, str):
            cmd = cmd.split()
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        if description:
            print_success(description)
        
        return True, result.stdout
    
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {' '.join(cmd)}")
        print(f"  Error: {e.stderr}")
        return False, e.stderr
    
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        return False, ""


def check_python_version():
    """Verify Python 3.8+"""
    print_step("Checking Python version...")
    
    version_info = sys.version_info
    version_str = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
    
    if version_info.major < 3 or (version_info.major == 3 and version_info.minor < 8):
        print_error(f"Python 3.8+ required, found {version_str}")
        return False
    
    print_success(f"Python {version_str}")
    return True


def install_backend_dependencies():
    """Install Python packages for backend"""
    print_header("Installing Backend Dependencies")
    
    packages = [
        ("librosa", "librosa==0.10.0", "Audio processing library"),
        ("scipy", "scipy==1.11.0", "Scientific computing"),
        ("websockets", "websockets==11.0.3", "WebSocket support"),
    ]
    
    for import_name, package_name, description in packages:
        print_step(f"Installing {description}...")
        
        success, _ = run_command(
            [sys.executable, "-m", "pip", "install", package_name, "-q"],
            ""
        )
        
        if success:
            print_success(f"Installed {package_name}")
        else:
            print_warning(f"Failed to install {package_name}, continuing...")
    
    print("\n" + "=" * 50)
    print("Installing requirements.txt...")
    success, _ = run_command(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
        ""
    )
    
    if success:
        print_success("All backend dependencies installed")
    else:
        print_warning("Some dependencies failed to install")
    
    return True


def check_npm():
    """Check if npm is available"""
    try:
        result = subprocess.run(
            ["npm", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False, None


def setup_frontend():
    """Setup frontend dependencies"""
    print_header("Setting Up Frontend")
    
    frontend_path = os.path.join("..", "frontend")
    
    if not os.path.exists(frontend_path):
        print_warning("Frontend directory not found")
        return False
    
    has_npm, npm_version = check_npm()
    
    if not has_npm:
        print_warning("npm not found. Frontend setup skipped.")
        print("           Install Node.js from https://nodejs.org/")
        return False
    
    print_success(f"npm {npm_version.split()[0]}")
    
    os.chdir(frontend_path)
    print_step("Checking frontend dependencies...")
    
    success, output = run_command(
        [sys.executable, "-m", "pip", "show", "axios"],
        ""
    )
    
    if "axios" not in output:
        print_step("Installing axios...")
        run_command(["npm", "install", "axios", "-q"], "")
    
    print_success("Frontend dependencies ready")
    os.chdir("..")
    
    return True


def verify_backend_setup():
    """Verify backend files are in place"""
    print_header("Verifying Backend Setup")
    
    required_files = [
        ("services/stt_service.py", "STT service with preprocessing"),
        ("services/tts_service.py", "TTS service with SSML"),
        ("services/audio_preprocessing.py", "Audio preprocessing module"),
        ("routers/interruption_ws.py", "WebSocket for interruption"),
        ("main.py", "FastAPI main app"),
        (".env.example", "Environment template"),
    ]
    
    all_exist = True
    
    for filepath, description in required_files:
        if os.path.exists(filepath):
            print_success(f"✓ {description}")
        else:
            print_error(f"✗ Missing: {description} ({filepath})")
            all_exist = False
    
    return all_exist


def print_next_steps():
    """Print setup completion instructions"""
    print_header("Setup Complete! 🎉")
    
    print("\n📝 NEXT STEPS:\n")
    
    print("1️⃣  Backend Configuration:")
    print("   • Edit or create .env file with your Azure credentials:")
    print("     AZURE_SPEECH_KEY=your_key_here")
    print("     AZURE_SPEECH_REGION=southeastasia\n")
    
    print("2️⃣  Start Backend Server:")
    print("   • Windows: python -m uvicorn backend.main:app --reload")
    print("   • Linux/Mac: python3 -m uvicorn backend.main:app --reload\n")
    
    print("3️⃣  Integrate Frontend (see ENHANCEMENT_GUIDE.md):")
    print("   • Import InterruptionHandler in VoiceAssistant.jsx")
    print("   • Add enhanced audio constraints to startRecording()")
    print("   • Setup TTS interruption detection\n")
    
    print("4️⃣  Start Frontend (in frontend/ directory):")
    print("   • npm run dev\n")
    
    print("5️⃣  Test the Features:")
    print("   • Open http://localhost:5173")
    print("   • Try speaking to the assistant")
    print("   • Interrupt the TTS by speaking again\n")
    
    print("📚 Full Documentation:")
    print("   • See ENHANCEMENT_GUIDE.md for detailed integration instructions\n")
    
    print("🐛 Troubleshooting:")
    print("   • STT not clear? Check microphone: sudo alsamixer (Linux)")
    print("   • WebSocket connection fails? Ensure backend is running on port 8000")
    print("   • Librosa import error? Try: pip install --upgrade librosa\n")


def main():
    """Main setup function"""
    print("\n")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║  Banking Voice Assistant - Enhancement Setup 🎙️           ║")
    print("║                                                            ║")
    print("║  Features:                                                 ║")
    print("║  ✅ Interruption logic (WebSocket VAD)                    ║")
    print("║  ✅ Advanced STT preprocessing                            ║")
    print("║  ✅ Humanized TTS with SSML                               ║")
    print("╚════════════════════════════════════════════════════════════╝\n")
    
    # Change to backend directory
    original_dir = os.getcwd()
    backend_dir = os.path.join(original_dir, "backend")
    
    if not os.path.exists(backend_dir):
        print_error("backend/ directory not found!")
        print("Please run this script from the project root directory")
        sys.exit(1)
    
    os.chdir(backend_dir)
    
    try:
        # Step 1: Check Python
        if not check_python_version():
            sys.exit(1)
        
        print()
        
        # Step 2: Install backend dependencies
        install_backend_dependencies()
        
        # Step 3: Setup frontend
        os.chdir(original_dir)
        setup_frontend()
        
        # Step 4: Verify setup
        os.chdir(backend_dir)
        if verify_backend_setup():
            print("\n✅ All files verified!")
        else:
            print_warning("Some files are missing or not set up correctly")
        
        # Step 5: Print completion message
        os.chdir(original_dir)
        print_next_steps()
        
        print("=" * 60)
        print("Setup script completed. Good luck! 🚀\n")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
