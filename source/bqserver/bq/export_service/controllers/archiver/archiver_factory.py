from __future__ import annotations

from io import StringIO
from lxml import etree
import os
from typing import Dict, Type, Any, BinaryIO, TextIO, Union
from abc import ABC, abstractmethod


class AbstractArchiver(ABC):
    """Abstract base class for file archivers."""
    
    def __init__(self) -> None:
        self.reader: Union[BinaryIO, TextIO, None] = None
        self.fileSize: int = 0

    def getContentType(self) -> str:
        return 'text/plain'

    def getFileExtension(self) -> str:
        return '.xml'
    
    def beginFile(self, file: Dict[str, Any]) -> None:
        if 'content' in file and file.get('content') is not None:
            self.reader = StringIO(file.get('content'))
            self.reader.seek(0, 2)
            self.fileSize = self.reader.tell()
            self.reader.seek(0)
        else:
            self.reader = open(file.get('path'), 'rb')
            # For binary files, get size from file stats
            if hasattr(self.reader, 'name'):
                self.fileSize = os.path.getsize(self.reader.name)
    
    def readBlock(self, block_size: int) -> Union[str, bytes]:
        return self.reader.read(block_size)
    
    def EOF(self) -> bool:
        return self.reader.tell() == self.fileSize
    
    def endFile(self) -> None:
        if self.reader:
            self.reader.close()
    
    def readEnding(self) -> str:
        return ''
    
    def close(self) -> None:
        pass
    
    def destinationPath(self, file: Dict[str, Any]) -> str:
        return file.get('outpath')


class ArchiverFactory:
    """Factory class for creating archiver instances."""
    
    @staticmethod
    def _get_supported_archivers() -> Dict[str, Type[AbstractArchiver]]:
        """Lazy import of archiver classes to avoid circular imports."""
        from bq.export_service.controllers.archiver.tar_archiver import TarArchiver
        from bq.export_service.controllers.archiver.zip_archiver import ZipArchiver
        from bq.export_service.controllers.archiver.gzip_archiver import GZipArchiver
        from bq.export_service.controllers.archiver.bz2_archiver import BZip2Archiver
        
        return {
            'tar': TarArchiver,
            'zip': ZipArchiver,
            'gzip': GZipArchiver,
            'bz2': BZip2Archiver,
        }
    
    @staticmethod
    def getClass(compressionType: str) -> AbstractArchiver:
        """Get an instance of the specified archiver type."""
        supported_archivers = ArchiverFactory._get_supported_archivers()
        archiver_class = supported_archivers.get(compressionType, AbstractArchiver)
        return archiver_class()

# !!! Old codes, kept for reference, not used in the current implementation !!!
# from io import StringIO
# from lxml import etree
# import os

# class AbstractArchiver():

#     def getContentType(self):
#         return 'text/plain'

#     def getFileExtension(self):
#         return '.xml'
    
#     def beginFile(self, file):
#         if 'content' in file and file.get('content') is not None:
#             self.reader = StringIO(file.get('content'))
#             self.reader.seek(0, 2)
#             self.fileSize = self.reader.tell()
#             self.reader.seek(0)
        
#         #elif 'xml' in file and file.get('path') is None:
#         #    self.reader = StringIO(etree.tostring(file.get('xml')))
#         #    self.reader.seek(0, 2)
#         #    self.fileSize = self.reader.tell()
#         #    self.reader.seek(0)

#         else:
#             self.reader = open(file.get('path'), 'rb')

#         return
    
#     def readBlock(self, block_size):
#         return self.reader.read(block_size)
    
#     def EOF(self):
#         return self.reader.tell()==self.fileSize
    
#     def endFile(self):
#         self.reader.close()
#         return
    
#     def readEnding(self):
#         return ''
    
#     def close(self):
#         return
    
#     def destinationPath(self, file):
#         return file.get('outpath')

# class ArchiverFactory():
    
#     from bq.export_service.controllers.archiver.tar_archiver import TarArchiver
#     from bq.export_service.controllers.archiver.zip_archiver import ZipArchiver
#     from bq.export_service.controllers.archiver.gzip_archiver import GZipArchiver
#     from bq.export_service.controllers.archiver.bz2_archiver import BZip2Archiver

#     supportedArchivers = {
#         'tar'  :   TarArchiver,
#         'zip'  :   ZipArchiver,
#         'gzip' :   GZipArchiver,
#         'bz2'  :   BZip2Archiver,
#     }  
    
#     @staticmethod
#     def getClass(compressionType):
#         archiver = ArchiverFactory.supportedArchivers.get(compressionType)
#         archiver = AbstractArchiver if archiver is None else archiver  

#         return archiver()
