package com.kinlin.ai.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.stream.Stream;
import lombok.Data;

/**
 * 文件服务类
 * 处理文件上传和存储
 */
@Slf4j
@Service
public class FileService {

    @Value("${app.upload.dir:uploads}")
    private String uploadDir;

    @Value("${app.upload.max-size:10485760}") // 10MB
    private long maxFileSize;

    /**
     * 保存上传的文件
     */
    public String saveFile(MultipartFile file, String subDir) throws IOException {
        // 验证文件大小
        if (file.getSize() > maxFileSize) {
            throw new IllegalArgumentException("文件大小超过限制: " + maxFileSize / 1024 / 1024 + "MB");
        }

        // 创建上传目录
        Path uploadPath = Paths.get(uploadDir, subDir);
        Files.createDirectories(uploadPath);

        // 生成唯一文件名
        String originalFilename = file.getOriginalFilename();
        String extension = "";
        if (originalFilename != null && originalFilename.contains(".")) {
            extension = originalFilename.substring(originalFilename.lastIndexOf("."));
        }
        String filename = UUID.randomUUID().toString() + extension;

        // 保存文件
        Path filePath = uploadPath.resolve(filename);
        Files.copy(file.getInputStream(), filePath, StandardCopyOption.REPLACE_EXISTING);

        log.info("File saved: {}", filePath);
        return subDir + "/" + filename;
    }

    /**
     * 删除文件
     */
    public void deleteFile(String filePath) throws IOException {
        Path path = Paths.get(uploadDir, filePath);
        if (Files.exists(path)) {
            Files.delete(path);
            log.info("File deleted: {}", path);
        }
    }

    /**
     * 获取文件路径
     */
    public Path getFilePath(String filePath) {
        return Paths.get(uploadDir, filePath);
    }

    /**
     * 检查文件是否存在
     */
    public boolean fileExists(String filePath) {
        return Files.exists(Paths.get(uploadDir, filePath));
    }

    /**
     * 获取文件列表
     */
    public List<FileInfo> listFiles(String type) throws IOException {
        List<FileInfo> files = new ArrayList<>();
        Path typePath = Paths.get(uploadDir, type);
        
        if (!Files.exists(typePath)) {
            return files;
        }
        
        try (Stream<Path> paths = Files.walk(typePath, 1)) {
            paths.filter(Files::isRegularFile)
                 .forEach(path -> {
                     try {
                         FileInfo info = new FileInfo();
                         info.setId(UUID.randomUUID().toString());
                         info.setName(path.getFileName().toString());
                         info.setPath(type + "/" + path.getFileName().toString());
                         info.setSize(Files.size(path));
                         info.setType(Files.probeContentType(path));
                         info.setUploadTime(java.time.Instant.ofEpochMilli(
                             Files.getLastModifiedTime(path).toMillis()).toString());
                         files.add(info);
                     } catch (IOException e) {
                         log.error("Error reading file info: {}", path, e);
                     }
                 });
        }
        
        return files;
    }

    /**
     * 文件信息DTO
     */
    @lombok.Data
    public static class FileInfo {
        private String id;
        private String name;
        private String path;
        private long size;
        private String type;
        private String uploadTime;
    }
}

