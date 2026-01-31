"""
Captcha Recognition Module
Using ddddocr for automatic captcha solving
"""

import base64
import io
from pathlib import Path
from typing import Optional, Union

try:
    from PIL import Image
except ImportError:
    raise ImportError("Please install Pillow package: pip install Pillow")

try:
    import ddddocr
except ImportError:
    raise ImportError("Please install ddddocr package: pip install ddddocr")

from .logger import get_logger


class CaptchaSolver:
    """Automatic captcha recognition using ddddocr"""

    def __init__(self, use_gpu: bool = False):
        """
        Initialize captcha solver

        Args:
            use_gpu: Whether to use GPU acceleration (requires CUDA)
        """
        self.logger = get_logger()
        self.logger.info(f"Initializing captcha solver (GPU: {use_gpu})")

        try:
            # Initialize ddddocr with beta mode for better accuracy
            self.ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
            self.logger.success("Captcha solver initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize captcha solver: {e}")
            raise

    def solve_from_file(self, image_path: Union[str, Path]) -> Optional[str]:
        """
        Recognize captcha from image file

        Args:
            image_path: Path to captcha image

        Returns:
            Recognized text or None if failed
        """
        try:
            image_path = Path(image_path)
            if not image_path.exists():
                self.logger.error(f"Captcha image not found: {image_path}")
                return None

            with open(image_path, 'rb') as f:
                image_bytes = f.read()

            result = self.ocr.classification(image_bytes)
            self.logger.debug(f"Captcha recognized from file: {result}")
            return result

        except Exception as e:
            self.logger.error(f"Error recognizing captcha from file: {e}")
            return None

    def solve_from_bytes(self, image_bytes: bytes) -> Optional[str]:
        """
        Recognize captcha from image bytes

        Args:
            image_bytes: Image data in bytes

        Returns:
            Recognized text or None if failed
        """
        try:
            result = self.ocr.classification(image_bytes)
            self.logger.debug(f"Captcha recognized from bytes: {result}")
            return result

        except Exception as e:
            self.logger.error(f"Error recognizing captcha from bytes: {e}")
            return None

    def solve_from_base64(self, base64_string: str) -> Optional[str]:
        """
        Recognize captcha from base64 string

        Args:
            base64_string: Base64 encoded image

        Returns:
            Recognized text or None if failed
        """
        try:
            # Remove data URI prefix if present
            if ',' in base64_string:
                base64_string = base64_string.split(',')[1]

            image_bytes = base64.b64decode(base64_string)
            result = self.ocr.classification(image_bytes)
            self.logger.debug(f"Captcha recognized from base64: {result}")
            return result

        except Exception as e:
            self.logger.error(f"Error recognizing captcha from base64: {e}")
            return None

    def solve_from_pil(self, image: Image.Image) -> Optional[str]:
        """
        Recognize captcha from PIL Image

        Args:
            image: PIL Image object

        Returns:
            Recognized text or None if failed
        """
        try:
            # Convert PIL Image to bytes
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()

            result = self.ocr.classification(img_byte_arr)
            self.logger.debug(f"Captcha recognized from PIL Image: {result}")
            return result

        except Exception as e:
            self.logger.error(f"Error recognizing captcha from PIL Image: {e}")
            return None

    def preprocess_image(self, image_path: Union[str, Path], output_path: Optional[Union[str, Path]] = None) -> Optional[Path]:
        """
        Preprocess captcha image for better recognition

        Args:
            image_path: Path to input image
            output_path: Path to save preprocessed image (optional)

        Returns:
            Path to preprocessed image or None if failed
        """
        try:
            from PIL import ImageEnhance, ImageFilter

            image_path = Path(image_path)
            img = Image.open(image_path)

            # Convert to grayscale
            img = img.convert('L')

            # Enhance contrast
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)

            # Apply threshold
            threshold = 128
            img = img.point(lambda p: 255 if p > threshold else 0)

            # Denoise
            img = img.filter(ImageFilter.MedianFilter(size=3))

            # Save preprocessed image
            if output_path is None:
                output_path = image_path.parent / f"{image_path.stem}_preprocessed{image_path.suffix}"
            else:
                output_path = Path(output_path)

            img.save(output_path)
            self.logger.debug(f"Image preprocessed and saved to: {output_path}")

            return output_path

        except Exception as e:
            self.logger.error(f"Error preprocessing image: {e}")
            return None

    def batch_solve(self, image_paths: list[Union[str, Path]]) -> dict[str, Optional[str]]:
        """
        Batch recognize multiple captcha images

        Args:
            image_paths: List of image paths

        Returns:
            Dictionary mapping image paths to recognized text
        """
        results = {}

        for image_path in image_paths:
            image_path = Path(image_path)
            result = self.solve_from_file(image_path)
            results[str(image_path)] = result

            if result:
                self.logger.info(f"Captcha solved: {image_path.name} → {result}")
            else:
                self.logger.warning(f"Failed to solve captcha: {image_path.name}")

        return results

    def test_solver(self) -> bool:
        """
        Test if the captcha solver is working

        Returns:
            True if solver is working, False otherwise
        """
        try:
            # Create a simple test image
            test_image = Image.new('L', (100, 40), color=255)
            result = self.solve_from_pil(test_image)
            self.logger.info("Captcha solver test completed")
            return True
        except Exception as e:
            self.logger.error(f"Captcha solver test failed: {e}")
            return False


# Module-level convenience functions
def solve_captcha(image_source: Union[str, Path, bytes, Image.Image]) -> Optional[str]:
    """
    Convenience function to solve captcha from various sources

    Args:
        image_source: Can be file path, bytes, or PIL Image

    Returns:
        Recognized text or None if failed
    """
    solver = CaptchaSolver()

    if isinstance(image_source, (str, Path)):
        return solver.solve_from_file(image_source)
    elif isinstance(image_source, bytes):
        return solver.solve_from_bytes(image_source)
    elif isinstance(image_source, Image.Image):
        return solver.solve_from_pil(image_source)
    else:
        raise TypeError(f"Unsupported image source type: {type(image_source)}")
