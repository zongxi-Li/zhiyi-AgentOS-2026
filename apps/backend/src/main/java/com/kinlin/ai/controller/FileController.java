package com.kinlin.ai.controller;

import com.kinlin.ai.service.FileService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.Resource;
import org.springframework.core.io.UrlResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;

/**
 * 文件上传控制器
 */
@Slf4j
@RestController
@RequestMapping("/files")
@RequiredArgsConstructor
public class FileController {

    private final FileService fileService;

    /**
     * 上传文件
     */
    @PostMapping("/upload")
    public ResponseEntity<FileUploadResponse> uploadFile(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "type", defaultValue = "general") String type
    ) {
        try {
            String filePath = fileService.saveFile(file, type);
            return ResponseEntity.ok(new FileUploadResponse(
                    filePath,
                    file.getOriginalFilename(),
                    file.getSize(),
                    file.getContentType()
            ));
        } catch (IOException e) {
            log.error("File upload failed", e);
            return ResponseEntity.internalServerError().build();
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(new FileUploadResponse(null, null, 0, null, e.getMessage()));
        }
    }

    /**
     * 下载文件
     */
    @GetMapping("/download/{type}/{filename:.+}")
    public ResponseEntity<Resource> downloadFile(
            @PathVariable String type,
            @PathVariable String filename
    ) {
        try {
            String filePath = type + "/" + filename;
            Path path = fileService.getFilePath(filePath);
            Resource resource = new UrlResource(path.toUri());

            if (resource.exists() && resource.isReadable()) {
                return ResponseEntity.ok()
                        .contentType(MediaType.APPLICATION_OCTET_STREAM)
                        .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + filename + "\"")
                        .body(resource);
            } else {
                return ResponseEntity.notFound().build();
            }
        } catch (Exception e) {
            log.error("File download failed", e);
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * 删除文件
     */
    @DeleteMapping("/{type}/{filename:.+}")
    public ResponseEntity<Void> deleteFile(
            @PathVariable String type,
            @PathVariable String filename
    ) {
        try {
            String filePath = type + "/" + filename;
            fileService.deleteFile(filePath);
            return ResponseEntity.ok().build();
        } catch (IOException e) {
            log.error("File delete failed", e);
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * 获取文件列表
     */
    @GetMapping
    public ResponseEntity<List<FileService.FileInfo>> getFileList(
            @RequestParam(value = "type", required = false) String type
    ) {
        try {
            List<FileService.FileInfo> files = fileService.listFiles(type != null ? type : "general");
            return ResponseEntity.ok(files);
        } catch (IOException e) {
            log.error("Get file list failed", e);
            return ResponseEntity.internalServerError().build();
        }
    }

    /**
     * 文件上传响应DTO
     */
    public record FileUploadResponse(
            String filePath,
            String originalFilename,
            long size,
            String contentType,
            String error
    ) {
        public FileUploadResponse(String filePath, String originalFilename, long size, String contentType) {
            this(filePath, originalFilename, size, contentType, null);
        }
    }
}

